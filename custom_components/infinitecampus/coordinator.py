"""Coordinator for Infinite Campus."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    InfiniteCampusAuthError,
    InfiniteCampusClient,
    InfiniteCampusConnectionError,
    InfiniteCampusError,
)
from .const import DEFAULT_UPDATE_INTERVAL

TERM_GRADE_PRIORITY = [
    "Quarter Grade",
    "Semester Grade",
    "Trimester Grade",
    "Term Grade",
]
FINAL_GRADE_PRIORITY = ["Final Grade"]
TERM_SLOT_COUNT = 4

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Course:
    """Course schedule entry."""

    section_id: int
    course_name: str
    teacher: str | None
    period: str | None
    start_time: str | None
    end_time: str | None
    room: str | None
    term_id: int | None


@dataclass(slots=True)
class CourseGrade:
    """Grade summary for a course."""

    section_id: int
    course_name: str
    score_raw: str | None
    score_numeric: float | None
    task_name: str | None
    current_term_seq: int | None
    term_grades: dict[int, dict[str, Any]]
    final_grade: dict[str, Any]


@dataclass(slots=True)
class StudentSnapshot:
    """Aggregated data for a student."""

    person_id: int
    name: str
    grade_level: str | None
    school_name: str | None
    term_id: int | None
    current_term_seq: int | None
    courses: list[Course]
    course_grades: dict[int, CourseGrade]
    overall_grade: float | str | None
    missing_assignments: int | None
    missing_assignments_by_term: dict[int, int | None]
    missing_assignments_by_course: dict[str, list[dict[str, Any]]]
    missing_assignments_list: list[dict[str, Any]]
    assignments_total: int | None
    assignments_by_course: dict[str, list[dict[str, Any]]]
    assignments_list: list[dict[str, Any]]
    failed_assignments_total: int | None
    failed_assignments_by_course: dict[str, list[dict[str, Any]]]
    failed_assignments_list: list[dict[str, Any]]
    attendance_total_absent: int | None
    attendance_total_tardy: int | None
    attendance_by_course: dict[str, dict[str, int]]


class InfiniteCampusDataUpdateCoordinator(
    DataUpdateCoordinator[dict[int, StudentSnapshot]]
):
    """Coordinator for Infinite Campus data."""

    def __init__(self, hass: HomeAssistant, client: InfiniteCampusClient) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name="Infinite Campus",
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> dict[int, StudentSnapshot]:
        try:
            today = dt_util.now().date()
            date_str = today.isoformat()
            students = await self._client.async_get_students()
            snapshots: dict[int, StudentSnapshot] = {}

            for student in students:
                person_id = int(student.get("personID"))
                name = _join_name(
                    student.get("firstName"),
                    student.get("middleName"),
                    student.get("lastName"),
                )
                grade_level = None
                school_name = None
                enrollments = student.get("enrollments") or []
                if enrollments:
                    grade_level = enrollments[0].get("grade")
                    school_name = enrollments[0].get("schoolName")

                roster = await self._client.async_get_roster(person_id, date_str)
                term_id = _find_current_term_id(roster, today)
                roster_terms = _extract_terms_from_roster(roster)
                courses = _extract_courses(roster, term_id)
                course_map = {course.section_id: course.course_name for course in courses}

                grades_overview = await self._client.async_get_grades_overview(
                    person_id
                )
                term_seq_by_id = _extract_term_sequence_map(grades_overview)
                current_term_seq = term_seq_by_id.get(term_id) if term_id else None
                if current_term_seq is None and term_seq_by_id:
                    current_term_seq = max(term_seq_by_id.values())

                course_grades = _extract_course_grades_from_overview(
                    grades_overview,
                    current_term_seq,
                    courses,
                    term_seq_by_id,
                )
                if not course_grades:
                    course_grades = await _fetch_course_grades(
                        self._client, person_id, courses, current_term_seq
                    )

                missing_assignments = None
                missing_items: list[dict[str, Any]] = []
                if term_id is not None:
                    missing_assignments = await self._client.async_get_missing_total(
                        person_id, term_id
                    )
                    missing_items = await self._client.async_get_missing_assignments(
                        person_id, term_id
                    )
                missing_assignments_by_term = await _fetch_missing_assignment_totals(
                    self._client,
                    person_id,
                    roster_terms,
                    today,
                    term_id,
                    missing_assignments,
                )
                missing_assignments_list = _normalize_assignments(
                    missing_items or [], term_id, course_map
                )
                missing_assignments_by_course = _group_assignments_by_course(
                    missing_assignments_list
                )

                assignments_payload = await self._client.async_get_assignments_list(
                    person_id
                )
                assignments_list = _normalize_assignments(
                    assignments_payload or [], term_id, course_map
                )
                assignments_by_course = _group_assignments_by_course(assignments_list)
                assignments_total = len(assignments_list)
                failed_assignments_list = _filter_failed_assignments(assignments_list)
                failed_assignments_by_course = _group_assignments_by_course(
                    failed_assignments_list
                )
                failed_assignments_total = len(failed_assignments_list)

                enrollment_id = _current_enrollment_id(student)
                attendance_by_course: dict[str, dict[str, int]] = {}
                if enrollment_id is not None:
                    attendance_payload = await self._client.async_get_attendance_events(
                        person_id, enrollment_id
                    )
                    (
                        attendance_by_course,
                        attendance_total_absent,
                        attendance_total_tardy,
                    ) = _summarize_attendance(attendance_payload or [], course_map)
                else:
                    attendance_total_absent = 0
                    attendance_total_tardy = 0

                snapshots[person_id] = StudentSnapshot(
                    person_id=person_id,
                    name=name,
                    grade_level=grade_level,
                    school_name=school_name,
                    term_id=term_id,
                    current_term_seq=current_term_seq,
                    courses=courses,
                    course_grades=course_grades,
                    overall_grade=_compute_overall_grade(course_grades),
                    missing_assignments=(
                        missing_assignments_by_term.get(current_term_seq or 0)
                        if current_term_seq is not None
                        else (
                            missing_assignments
                            if missing_assignments is not None
                            else len(missing_assignments_list)
                        )
                    ),
                    missing_assignments_by_term=missing_assignments_by_term,
                    missing_assignments_by_course=missing_assignments_by_course,
                    missing_assignments_list=missing_assignments_list,
                    assignments_total=assignments_total,
                    assignments_by_course=assignments_by_course,
                    assignments_list=assignments_list,
                    failed_assignments_total=failed_assignments_total,
                    failed_assignments_by_course=failed_assignments_by_course,
                    failed_assignments_list=failed_assignments_list,
                    attendance_total_absent=attendance_total_absent,
                    attendance_total_tardy=attendance_total_tardy,
                    attendance_by_course=attendance_by_course,
                )

            return snapshots
        except InfiniteCampusAuthError as err:
            raise UpdateFailed("Invalid authentication") from err
        except (InfiniteCampusConnectionError, InfiniteCampusError) as err:
            raise UpdateFailed(str(err)) from err


def _join_name(first: str | None, middle: str | None, last: str | None) -> str:
    parts = [p for p in [first, middle, last] if p]
    return " ".join(parts) if parts else "Student"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _find_current_term_id(roster: list[dict[str, Any]], today: date) -> int | None:
    candidates: list[dict[str, Any]] = []
    for course in roster:
        for placement in course.get("sectionPlacements", []) or []:
            term = placement.get("term") or {}
            start = _parse_date(term.get("startDate"))
            end = _parse_date(term.get("endDate"))
            if start and end and start <= today <= end:
                if term.get("isPrimary"):
                    return _coerce_int(term.get("termID"))
                candidates.append(term)
    for term in candidates:
        term_id = _coerce_int(term.get("termID"))
        if term_id is not None:
            return term_id
    for course in roster:
        for placement in course.get("sectionPlacements", []) or []:
            term = placement.get("term") or {}
            term_id = _coerce_int(term.get("termID"))
            if term_id is not None:
                return term_id
    return None


def _current_enrollment_id(student: dict[str, Any]) -> int | None:
    enrollments = student.get("enrollments") or []
    if not enrollments:
        return None
    return _coerce_int(enrollments[0].get("enrollmentID"))


def _extract_courses(
    roster: list[dict[str, Any]], term_id: int | None
) -> list[Course]:
    courses: list[Course] = []
    for course in roster:
        section_id = _coerce_int(course.get("sectionID"))
        if section_id is None:
            continue
        course_name = course.get("courseName") or "Course"
        teacher = course.get("teacherDisplay")
        room = course.get("roomName")
        period = None
        start_time = None
        end_time = None
        course_term_id = term_id
        placements = course.get("sectionPlacements") or []
        if placements:
            placement = _select_current_placement(placements, term_id)
            if placement:
                period = placement.get("periodName")
                start_time = placement.get("startTime")
                end_time = placement.get("endTime")
                room = placement.get("roomName") or room
                course_term_id = _coerce_int(placement.get("termID")) or course_term_id
        courses.append(
            Course(
                section_id=section_id,
                course_name=course_name,
                teacher=teacher,
                period=period,
                start_time=start_time,
                end_time=end_time,
                room=room,
                term_id=course_term_id,
            )
        )
    return courses


def _extract_terms_from_roster(
    roster: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    terms: dict[int, dict[str, Any]] = {}
    for course in roster:
        for placement in course.get("sectionPlacements", []) or []:
            term = placement.get("term") or {}
            term_id = _coerce_int(term.get("termID"))
            term_seq = _coerce_int(term.get("seq")) or _coerce_int(term.get("termSeq"))
            if term_id is None or term_seq is None or term_seq < 1 or term_seq > TERM_SLOT_COUNT:
                continue
            terms[term_seq] = {
                "term_id": term_id,
                "start_date": _parse_date(term.get("startDate")),
                "end_date": _parse_date(term.get("endDate")),
                "name": term.get("termName"),
            }
    return terms


def _extract_term_sequence_map(payload: list[dict[str, Any]]) -> dict[int, int]:
    term_seq_by_id: dict[int, int] = {}
    for enrollment in payload:
        for term in enrollment.get("terms", []) or []:
            term_id = _coerce_int(term.get("termID"))
            term_seq = _coerce_int(term.get("termSeq"))
            if term_id is None or term_seq is None:
                continue
            term_seq_by_id[term_id] = term_seq
    return term_seq_by_id


def _extract_course_grades_from_overview(
    payload: list[dict[str, Any]],
    current_term_seq: int | None,
    courses: list[Course],
    term_seq_by_id: dict[int, int],
) -> dict[int, CourseGrade]:
    course_name_map = {course.section_id: course.course_name for course in courses}
    grades: dict[int, CourseGrade] = {}
    for enrollment in payload:
        for course in enrollment.get("courses", []) or []:
            section_id = _coerce_int(course.get("sectionID"))
            if section_id is None:
                continue
            term_grades = _extract_term_grades_from_tasks(
                course.get("gradingTasks") or [],
                term_seq_by_id,
            )
            final_grade = _select_final_grade_task(course.get("gradingTasks") or [])
            current_grade = term_grades.get(current_term_seq or 0, _blank_term_grade())
            course_name = course.get("courseName") or course_name_map.get(
                section_id, "Course"
            )
            grades[section_id] = CourseGrade(
                section_id=section_id,
                course_name=course_name,
                score_raw=current_grade.get("score_raw"),
                score_numeric=current_grade.get("score_numeric"),
                task_name=current_grade.get("task_name"),
                current_term_seq=current_term_seq,
                term_grades=term_grades,
                final_grade=final_grade or _blank_term_grade(),
            )
    return grades


def _extract_term_grades_from_tasks(
    tasks: list[dict[str, Any]],
    term_seq_by_id: dict[int, int],
) -> dict[int, dict[str, Any]]:
    term_grades = {seq: _blank_term_grade() for seq in range(1, TERM_SLOT_COUNT + 1)}
    tasks_by_term_seq: dict[int, list[dict[str, Any]]] = {}
    for task in tasks:
        term_id = _coerce_int(task.get("termID"))
        if term_id is None:
            continue
        term_seq = term_seq_by_id.get(term_id)
        if term_seq is None or term_seq not in term_grades:
            continue
        tasks_by_term_seq.setdefault(term_seq, []).append(task)

    for term_seq, term_tasks in tasks_by_term_seq.items():
        selected = _select_term_task(term_tasks)
        if selected is not None:
            term_grades[term_seq] = selected
    return term_grades


def _blank_term_grade() -> dict[str, Any]:
    return {
        "score_raw": None,
        "score_numeric": None,
        "task_name": None,
        "percent": None,
    }


def _select_term_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _select_priority_task(tasks, TERM_GRADE_PRIORITY)


def _select_final_grade_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _select_priority_task(tasks, FINAL_GRADE_PRIORITY)


def _select_priority_task(
    tasks: list[dict[str, Any]],
    names: list[str],
) -> dict[str, Any] | None:
    fallback: dict[str, Any] | None = None
    for name in names:
        for task in tasks:
            task_name = _task_name(task)
            if task_name != name:
                continue
            selected = _build_selected_task(task, task_name)
            if _has_grade_value(selected):
                return selected
            if fallback is None:
                fallback = selected
    return fallback


def _task_name(task: dict[str, Any]) -> str | None:
    return task.get("taskName") or task.get("name")


def _build_selected_task(task: dict[str, Any], task_name: str | None) -> dict[str, Any]:
    score_raw = _task_score_value(task)
    return {
        "score_raw": score_raw,
        "score_numeric": _parse_numeric_score(score_raw),
        "task_name": task_name,
        "percent": _task_percent_value(task),
    }


def _task_score_value(task: dict[str, Any]) -> str | None:
    for key in ("score", "progressScore", "scoreMark"):
        value = task.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _task_percent_value(task: dict[str, Any]) -> float | None:
    for key in ("percent", "progressPercent"):
        value = task.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            parsed = _parse_numeric_score(value)
            if parsed is not None:
                return parsed
    return None


def _has_grade_value(selected: dict[str, Any]) -> bool:
    return selected.get("score_raw") is not None or selected.get("percent") is not None


def _normalize_assignments(
    assignments: list[dict[str, Any]],
    term_id: int | None,
    course_map: dict[int, str],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in assignments:
        raw_term_ids = item.get("termIDs") or []
        term_ids = [term for term in (_coerce_int(value) for value in raw_term_ids) if term]
        if term_id is not None and term_ids and term_id not in term_ids:
            continue
        section_id = _coerce_int(item.get("sectionID"))
        course_name = item.get("courseName")
        if not course_name and section_id is not None:
            course_name = course_map.get(section_id)
        if not course_name:
            course_name = "Unknown Course"
        normalized.append(
            {
                "course": course_name,
                "assignment": item.get("assignmentName"),
                "due_date": item.get("dueDate"),
                "assigned_date": item.get("assignedDate"),
                "score": item.get("score"),
                "score_points": item.get("scorePoints"),
                "score_percentage": item.get("scorePercentage"),
                "total_points": item.get("totalPoints"),
                "missing": item.get("missing"),
                "late": item.get("late"),
                "turned_in": item.get("turnedIn"),
                "not_graded": item.get("notGraded"),
                "section_id": section_id,
                "term_ids": term_ids,
            }
        )
    normalized.sort(key=_assignment_sort_key)
    return normalized


def _assignment_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("due_date") or ""),
        str(item.get("course") or ""),
        str(item.get("assignment") or ""),
    )


def _group_assignments_by_course(
    assignments: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in assignments:
        course_name = str(item.get("course") or "Unknown Course")
        grouped.setdefault(course_name, []).append(item)
    return grouped


async def _fetch_missing_assignment_totals(
    client: InfiniteCampusClient,
    person_id: int,
    roster_terms: dict[int, dict[str, Any]],
    today: date,
    current_term_id: int | None,
    current_term_total: int | None,
) -> dict[int, int | None]:
    totals = {seq: None for seq in range(1, TERM_SLOT_COUNT + 1)}
    tasks: list[tuple[int, asyncio.Task[int | None]]] = []

    for term_seq, term in roster_terms.items():
        start_date = term.get("start_date")
        if start_date is not None and start_date > today:
            continue

        term_id = _coerce_int(term.get("term_id"))
        if term_id is None:
            continue

        if current_term_id is not None and term_id == current_term_id and current_term_total is not None:
            totals[term_seq] = current_term_total
            continue

        tasks.append(
            (
                term_seq,
                asyncio.create_task(client.async_get_missing_total(person_id, term_id)),
            )
        )

    if tasks:
        results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        for (term_seq, _), result in zip(tasks, results, strict=False):
            if isinstance(result, Exception):
                continue
            totals[term_seq] = result

    return totals


def _filter_failed_assignments(
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        item
        for item in assignments
        if (percentage := _assignment_percentage(item)) is not None and percentage < 65
    ]


def _assignment_percentage(item: dict[str, Any]) -> float | None:
    score_percentage = _parse_numeric_score(item.get("score_percentage"))
    if score_percentage is not None:
        return score_percentage

    score_points = _parse_numeric_score(item.get("score_points"))
    total_points = _parse_numeric_score(item.get("total_points"))
    if score_points is not None and total_points not in (None, 0):
        return (score_points / total_points) * 100
    return None


def _summarize_attendance(
    payload: list[dict[str, Any]], course_map: dict[int, str]
) -> tuple[dict[str, dict[str, int]], int | None, int | None]:
    counts: dict[str, dict[str, int]] = {}
    total_absent = 0
    total_tardy = 0
    for calendar in payload:
        events = calendar.get("events") or []
        for event in events:
            kind = _attendance_kind(event)
            if kind is None:
                continue
            placements = event.get("sectionPlacements") or []
            for placement in placements:
                section_id = _coerce_int(placement.get("sectionID"))
                course_name = placement.get("courseName")
                if not course_name and section_id is not None:
                    course_name = course_map.get(section_id)
                if not course_name:
                    course_name = "Unknown Course"
                course_counts = counts.setdefault(course_name, {"absent": 0, "tardy": 0})
                course_counts[kind] += 1
                if kind == "absent":
                    total_absent += 1
                elif kind == "tardy":
                    total_tardy += 1
    return counts, total_absent, total_tardy


def _attendance_kind(event: dict[str, Any]) -> str | None:
    status = str(event.get("status") or "").upper()
    description = str(event.get("description") or "").lower()
    if status.startswith("A") or "absen" in description:
        return "absent"
    if status in ("T", "L") or "tardy" in description or "late" in description:
        return "tardy"
    return None


def _select_current_placement(
    placements: list[dict[str, Any]], term_id: int | None
) -> dict[str, Any] | None:
    if term_id is not None:
        for placement in placements:
            if _coerce_int(placement.get("termID")) == term_id:
                return placement
    return placements[0] if placements else None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


async def _fetch_course_grades(
    client: InfiniteCampusClient,
    person_id: int,
    courses: list[Course],
    current_term_seq: int | None,
) -> dict[int, CourseGrade]:
    results: dict[int, CourseGrade] = {}
    tasks = [
        _fetch_course_grade(client, person_id, course, current_term_seq)
        for course in courses
    ]
    if not tasks:
        return results
    for outcome in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(outcome, CourseGrade):
            results[outcome.section_id] = outcome
    return results


async def _fetch_course_grade(
    client: InfiniteCampusClient,
    person_id: int,
    course: Course,
    current_term_seq: int | None,
) -> CourseGrade | None:
    try:
        detail = await client.async_get_grade_detail(person_id, course.section_id)
    except InfiniteCampusError:
        return None
    term_grades = _extract_term_grades_from_detail(detail, course.term_id, current_term_seq)
    current_grade = term_grades.get(current_term_seq or 0, _blank_term_grade())
    return CourseGrade(
        section_id=course.section_id,
        course_name=course.course_name,
        score_raw=current_grade.get("score_raw"),
        score_numeric=current_grade.get("score_numeric"),
        task_name=current_grade.get("task_name"),
        current_term_seq=current_term_seq,
        term_grades=term_grades,
        final_grade=_blank_term_grade(),
    )


def _extract_term_grades_from_detail(
    detail: dict[str, Any],
    term_id: int | None,
    current_term_seq: int | None,
) -> dict[int, dict[str, Any]]:
    term_grades = {seq: _blank_term_grade() for seq in range(1, TERM_SLOT_COUNT + 1)}
    details = detail.get("details") or []
    tasks: list[dict[str, Any]] = []
    for entry in details:
        task = entry.get("task") or {}
        if term_id is not None and _coerce_int(task.get("termID")) != term_id:
            continue
        tasks.append(task)
    selected = _select_term_task(tasks)
    if selected is not None and current_term_seq in term_grades:
        term_grades[current_term_seq] = selected
    return term_grades


def _parse_numeric_score(score: Any) -> float | None:
    if score is None:
        return None
    if isinstance(score, (int, float)):
        return float(score)
    if isinstance(score, str):
        text = score.strip().rstrip("%")
        if not text:
            return None
        if re.match(r"^\d+(\.\d+)?$", text):
            try:
                return float(text)
            except ValueError:
                return None
    return None


def _latest_real_term_grade(grade: CourseGrade) -> dict[str, Any] | None:
    current_term = grade.current_term_seq
    if current_term in grade.term_grades:
        current = grade.term_grades[current_term]
        if _has_grade_value(current):
            return current
    for term_seq in sorted(grade.term_grades, reverse=True):
        selected = grade.term_grades[term_seq]
        if _has_grade_value(selected):
            return selected
    return None


def _compute_overall_grade(grades: dict[int, CourseGrade]) -> float | str | None:
    selected = [
        grade_data
        for grade in grades.values()
        if (grade_data := _latest_real_term_grade(grade)) is not None
    ]
    numbers = [
        grade_data["score_numeric"]
        for grade_data in selected
        if grade_data.get("score_numeric") is not None
    ]
    if numbers:
        return round(sum(numbers) / len(numbers), 2)
    raw = [grade_data["score_raw"] for grade_data in selected if grade_data.get("score_raw")]
    if raw:
        counts: dict[str, int] = {}
        for value in raw:
            counts[value] = counts.get(value, 0) + 1
        return max(counts, key=counts.get)
    return "In Progress"
