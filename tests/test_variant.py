import pytest

from hhlake.variant import display_skill, in_variant, is_c_cpp, is_education, normalize_skill, parse_skills, stacks

ROLE = "Программист, разработчик"


@pytest.mark.parametrize(
    "name",
    [
        "Программист C/С++",
        "Разработчик C++",
        "Ведущий программист C ++",
        "Ведущий программист с++",
        "Разработчик С",
        "C-разработчик",
        "Разработчик C (Linux Kernel, DPDK, SPDK)",
        "Ведущий разработчик (Golang, C)",
        "Embedded программист С/++",
        "Разработчик C\\Linux",
        "Разработчик C#/С (Linux/RDP-направление)",
        "Программист Си (STM32)",
        "Staff engineer (Си)",
        "Ведущий разработчик на Си под Linux (Data Plane)",
    ],
)
def test_c_cpp_names(name: str) -> None:
    assert is_c_cpp(name)


@pytest.mark.parametrize(
    "name",
    [
        "Разработчик C#",
        "Разработчик С #",
        "Программист 1 С",
        "Программист 1С",
        "Ведущий разработчик 1:С ERP",
        "Программист 1С ЗУП (блок C&B)",
        "Инженер-программист станков с ЧПУ",
        "Data Scientist (Middle) с переездом",
        "Программист .NET (редизайн системы c .Net Framework на .NET 6)",
        "IOS разработчик Objective C",
        "Objective-C developer",
        "Fullstack разработчик (C опытом интеграции/разработки амо срм)",
        "Программист-разработчик (С-подобные языки)",
        "Сиситемный аналитик",
        "Python Backend Developer",
    ],
)
def test_not_c_cpp_names(name: str) -> None:
    assert not is_c_cpp(name)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Преподаватель языка программирования С++", True),
        ("Автор работ по программированию C++", True),
        ('Наставник на курс "Разработчик С++"', True),
        ("Ментор С++ developer", True),
        ("Программный эксперт на курс «Мидл С++ разработчик»", True),
        ("Разработчик C++ (системы авторизации)", False),
        ("Разработчик C++", False),
    ],
)
def test_education_titles(name: str, expected: bool) -> None:
    assert is_education(name) is expected


def test_role_is_required() -> None:
    assert in_variant(ROLE, "Разработчик C++")
    assert not in_variant("Тестировщик", "Разработчик C++")
    assert not in_variant(ROLE, "Преподаватель C++")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" С++ ", "c++"),
        ("С", "c"),
        ("C/С++", "c/c++"),
        ("CMake", "cmake"),
        ("CMAKE", "cmake"),
        ("1С: Предприятие 8", "1с: предприятие 8"),
        ("ООП", "ооп"),
    ],
)
def test_normalize_skill(raw: str, expected: str) -> None:
    assert normalize_skill(raw) == expected


def test_display_keeps_case() -> None:
    assert display_skill(" С++ ") == "C++"
    assert display_skill("Linux") == "Linux"


def test_parse_skills_dedup_after_normalization() -> None:
    assert parse_skills("C++; Linux; С++;  ; Git; linux") == ["c++", "git", "linux"]


def test_stacks_sizes_match_binomials() -> None:
    skills = parse_skills("a; b; c; d; e")
    assert [len(stacks(skills, k)) for k in (1, 2, 3)] == [5, 10, 10]
    assert stacks(skills, 2)[0] == ("a", "b")
