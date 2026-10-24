"""Sensor platform for Infinite Campus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import (
    Course,
    CourseGrade,
    InfiniteCampusDataUpdateCoordinator,
    StudentSnapshot,
    attendance_today,
)


@dataclass(slots=True)
class StudentSensorDescription(SensorEntityDescription):
    """Describes Infinite Campus student sensors."""


SENSOR_DESCRIPTIONS: tuple[StudentSensorDescription, ...] = (
    StudentSensorDescription(
        key="overall_grade",
        name="Overall Grade",
        icon="mdi:school",
    ),
    StudentSensorDescription(
        key="missing_assignments",
        name="Missing Assignments",
        icon="mdi:alert",
    ),
    StudentSensorDescription(
        key="attendance",
        name="Attendance",
        icon="mdi:account-check",
    ),
    StudentSensorDescription(
        key="attendance_today",
        name="Attendance Today",
        icon="mdi:school",
        device_class=SensorDeviceClass.ENUM,
        options=["none", "tardy", "partial", "absent"],
    ),
    StudentSensorDescription(
        key="failed_assignments",
        name="Failed Assignments",
        icon="mdi:alert-circle",
    ),
    StudentSensorDescription(
        key="assignments",
        name="Assignments",
        icon="mdi:clipboard-text",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: InfiniteCampusDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[InfiniteCampusStudentSensor] = []
    course_entities: list[InfiniteCampusCourseSensor] = []
    seen_courses: set[tuple[int, int]] = set()
    for student in coordinator.data.values():
        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                InfiniteCampusStudentSensor(coordinator, student, description)
            )
        for course in student.courses:
            key = (student.person_id, course.section_id)
            if key in seen_courses:
                continue
            seen_courses.add(key)
            course_entities.append(
                InfiniteCampusCourseSensor(coordinator, student, course)
            )

    async_add_entities(entities + course_entities)


class InfiniteCampusStudentSensor(
    CoordinatorEntity[InfiniteCampusDataUpdateCoordinator], SensorEntity
):
    """Sensor for a student metric."""

    # The per-day list can exceed the recorder's attribute size limit;
    # the attendance calendar keeps that history instead.
    _unrecorded_attributes = frozenset({"days"})

    def __init__(
        self,
        coordinator: InfiniteCampusDataUpdateCoordinator,
        student: StudentSnapshot,
        description: StudentSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._person_id = student.person_id
        self._student_name = student.name
        self._attr_unique_id = f"{student.person_id}_{description.key}"
        self._attr_name = f"{student.name} {description.name}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._person_id))},
            name=self._student_name,
            manufacturer="Infinite Campus",
            model="Student",
        )

    @property
    def native_value(self) -> Any:
        student = self.coordinator.data.get(self._person_id)
        if not student:
            return None
        key = self.entity_description.key
        value: Any = None
        if key == "overall_grade":
            value = student.overall_grade
        elif key == "missing_assignments":
            value = student.missing_assignments
        elif key == "attendance":
            value = student.attendance_total_absent
        elif key == "attendance_today":
            today = attendance_today(student.attendance_days, dt_util.now().date())
            return today["status"] if today else "none"
        elif key == "failed_assignments":
            value = student.failed_assignments_total
        elif key == "assignments":
            value = student.assignments_total
        return _display_value(value)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.key == "overall_grade":
            value = self.native_value
            return "%" if isinstance(value, (int, float)) else None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        student = self.coordinator.data.get(self._person_id)
        if not student:
            return None
        key = self.entity_description.key
        if key == "overall_grade":
            courses = {
                grade.course_name: _course_grade_attributes(grade)
                for grade in student.course_grades.values()
            }
            return _with_na(
                {
                    "current_term": student.current_term_seq,
                    "courses": courses,
                    **courses,
                }
            )
        if key == "missing_assignments":
            return _with_na(
                {
                    "current_term": student.current_term_seq,
                    "term1": student.missing_assignments_by_term.get(1),
                    "term2": student.missing_assignments_by_term.get(2),
                    "term3": student.missing_assignments_by_term.get(3),
                    "term4": student.missing_assignments_by_term.get(4),
                    "assignments": student.missing_assignments_list,
                    "courses": student.missing_assignments_by_course,
                    **student.missing_assignments_by_course,
                }
            )
        if key == "attendance":
            return _with_na(
                {
                    "total_absent": student.attendance_total_absent,
                    "total_tardy": student.attendance_total_tardy,
                    "days": student.attendance_days,
                    "absent_days": _count_days(student.attendance_days, "absent"),
                    "partial_days": _count_days(student.attendance_days, "partial"),
                    "tardy_days": _count_days(student.attendance_days, "tardy"),
                    "courses": student.attendance_by_course,
                    **student.attendance_by_course,
                }
            )
        if key == "attendance_today":
            today = attendance_today(student.attendance_days, dt_util.now().date())
            if not today:
                return None
            return {
                "periods": today.get("periods"),
                "courses": today.get("courses"),
                "codes": today.get("codes"),
                "excused": today.get("excused"),
            }
        if key == "failed_assignments":
            return _with_na(
                {
                    "assignments": student.failed_assignments_list,
                    "courses": student.failed_assignments_by_course,
                    **student.failed_assignments_by_course,
                }
            )
        if key == "assignments":
            return _with_na(
                {
                    "assignments": student.assignments_list,
                    "courses": student.assignments_by_course,
                    **student.assignments_by_course,
                }
            )
        return None


class InfiniteCampusCourseSensor(
    CoordinatorEntity[InfiniteCampusDataUpdateCoordinator], SensorEntity
):
    """Sensor for a student's course grade."""

    _attr_icon = "mdi:book"

    def __init__(
        self,
        coordinator: InfiniteCampusDataUpdateCoordinator,
        student: StudentSnapshot,
        course: Course,
    ) -> None:
        super().__init__(coordinator)
        self._person_id = student.person_id
        self._student_name = student.name
        self._section_id = course.section_id
        self._course_name = course.course_name
        self._attr_unique_id = f"{student.person_id}_{course.section_id}_grade"
        self._attr_name = f"{student.name} {course.course_name}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._person_id))},
            name=self._student_name,
            manufacturer="Infinite Campus",
            model="Student",
        )

    @property
    def native_value(self) -> Any:
        grade = self._get_course_grade()
        return _display_value(_effective_course_grade_value(grade))

    @property
    def native_unit_of_measurement(self) -> str | None:
        grade = self._get_course_grade()
        if _effective_course_grade_is_numeric(grade):
            return "%"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        student = self.coordinator.data.get(self._person_id)
        if not student:
            return None
        course = next(
            (item for item in student.courses if item.section_id == self._section_id),
            None,
        )
        grade = student.course_grades.get(self._section_id)
        current = _current_term_grade(grade)
        attendance = student.attendance_by_course.get(self._course_name, {})
        return _with_na(
            {
                "course": self._course_name,
                "section_id": self._section_id,
                "teacher": course.teacher if course else None,
                "period": course.period if course else None,
                "room": course.room if course else None,
                "start_time": course.start_time if course else None,
                "end_time": course.end_time if course else None,
                "absences": attendance.get("absent", 0),
                "tardies": attendance.get("tardy", 0),
                "current_term": grade.current_term_seq if grade else None,
                "task": current.get("task_name") if current else None,
                "score_raw": current.get("score_raw") if current else None,
                "score_numeric": _clean_number(current["score_numeric"])
                if current and current.get("score_numeric") is not None
                else None,
                "score_percent": _clean_number(float(current["percent"]))
                if current and current.get("percent") is not None
                else None,
                "term1_grade": _term_grade_value(grade, 1),
                "term2_grade": _term_grade_value(grade, 2),
                "term3_grade": _term_grade_value(grade, 3),
                "term4_grade": _term_grade_value(grade, 4),
                "final_grade": _final_grade_value(grade),
                "term1_percent": _term_grade_percent(grade, 1),
                "term2_percent": _term_grade_percent(grade, 2),
                "term3_percent": _term_grade_percent(grade, 3),
                "term4_percent": _term_grade_percent(grade, 4),
                "final_percent": _final_grade_percent(grade),
            }
        )

    def _get_course_grade(self) -> CourseGrade | None:
        student = self.coordinator.data.get(self._person_id)
        if not student:
            return None
        return student.course_grades.get(self._section_id)


def _count_days(days: list[dict[str, Any]], status: str) -> int:
    return sum(1 for day in days or [] if day.get("status") == status)


def _course_grade_attributes(grade: CourseGrade) -> dict[str, Any]:
    current = _current_term_grade(grade)
    return {
        "current_term": grade.current_term_seq,
        "current_grade": _course_grade_value(grade),
        "task": current.get("task_name") if current else None,
        "term1_grade": _term_grade_value(grade, 1),
        "term2_grade": _term_grade_value(grade, 2),
        "term3_grade": _term_grade_value(grade, 3),
        "term4_grade": _term_grade_value(grade, 4),
        "final_grade": _final_grade_value(grade),
        "term1_percent": _term_grade_percent(grade, 1),
        "term2_percent": _term_grade_percent(grade, 2),
        "term3_percent": _term_grade_percent(grade, 3),
        "term4_percent": _term_grade_percent(grade, 4),
        "final_percent": _final_grade_percent(grade),
    }


def _current_term_grade(grade: CourseGrade | None) -> dict[str, Any] | None:
    if grade is None or grade.current_term_seq is None:
        return None
    return grade.term_grades.get(grade.current_term_seq)


def _course_grade_value(grade: CourseGrade | None) -> Any:
    current = _current_term_grade(grade)
    if not current:
        return None
    if current.get("score_numeric") is not None:
        return _clean_number(current["score_numeric"])
    if current.get("score_raw") is not None:
        return current.get("score_raw")
    if current.get("task_name") is not None:
        return "N/A"
    return None


def _effective_course_grade_value(grade: CourseGrade | None) -> Any:
    value = _course_grade_value(grade)
    if value != "N/A":
        return value
    final_value = _final_grade_value(grade)
    if final_value is not None:
        return final_value
    return value


def _effective_course_grade_is_numeric(grade: CourseGrade | None) -> bool:
    value = _effective_course_grade_value(grade)
    return isinstance(value, (int, float))


def _term_grade_value(grade: CourseGrade | None, term_seq: int) -> Any:
    if grade is None:
        return None
    term = grade.term_grades.get(term_seq)
    if not term:
        return None
    if term.get("score_numeric") is not None:
        return _clean_number(term["score_numeric"])
    return term.get("score_raw")


def _term_grade_percent(grade: CourseGrade | None, term_seq: int) -> float | None:
    if grade is None:
        return None
    term = grade.term_grades.get(term_seq)
    if not term:
        return None
    percent = term.get("percent")
    if isinstance(percent, (int, float)):
        return _clean_number(float(percent))
    return None


def _final_grade_value(grade: CourseGrade | None) -> Any:
    if grade is None:
        return None
    final = grade.final_grade
    if final.get("score_numeric") is not None:
        return _clean_number(final["score_numeric"])
    return final.get("score_raw")


def _final_grade_percent(grade: CourseGrade | None) -> float | None:
    if grade is None:
        return None
    percent = grade.final_grade.get("percent")
    if isinstance(percent, (int, float)):
        return _clean_number(float(percent))
    return None


def _clean_number(value: float) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _display_value(value: Any) -> Any:
    if value is None:
        return "N/A"
    return value


def _with_na(value: Any) -> Any:
    if value is None:
        return "N/A"
    if isinstance(value, dict):
        return {key: _with_na(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_with_na(item) for item in value]
    return value
