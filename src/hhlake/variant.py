import re
from itertools import combinations

ROLE = "Программист, разработчик"
ROLE_BYTES = ROLE.encode()

_WORD = "A-Za-zА-Яа-яЁё0-9_"
CPP_RE = re.compile(r"[CcСс] ?\+\+")
C_RE = re.compile(rf"(?<![{_WORD}\-+#.:])(?<!1 )(?<!Objective )[CС](?![{_WORD}+#&])(?! *#)(?! опыт)(?!-подобн)")
SI_RE = re.compile(rf"(?<![{_WORD}])Си(?![{_WORD}])")
EDU_RE = re.compile(r"(?<![а-яё])(преподавател[а-яё]*|автор|наставник|ментор|эксперт на курс)(?![а-яё])")
CYRILLIC_RE = re.compile("[А-Яа-яЁё]")


def is_c_cpp(name: str) -> bool:
    return bool(CPP_RE.search(name) or C_RE.search(name) or SI_RE.search(name))


def is_education(name: str) -> bool:
    return bool(EDU_RE.search(name.lower()))


def in_variant(role: str, name: str) -> bool:
    return role == ROLE and is_c_cpp(name) and not is_education(name)


def display_skill(raw: str) -> str:
    skill = raw.strip()
    latin = skill.replace("С", "C").replace("с", "c")
    return skill if CYRILLIC_RE.search(latin) else latin


def normalize_skill(raw: str) -> str:
    return display_skill(raw).lower()


def parse_skills(key_skills: str) -> list[str]:
    skills = {normalize_skill(s) for s in key_skills.split(";")}
    skills.discard("")
    return sorted(skills)


def stacks(skills: list[str], size: int) -> list[tuple[str, ...]]:
    return list(combinations(skills, size))
