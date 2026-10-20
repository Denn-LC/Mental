from dataclasses import dataclass


@dataclass
class Question:
    id: str            # "<category>-<difficulty>-<seed>": enough to regenerate it
    seed: int
    text: str          # "615 − 197", "18 × 6 = 9 × ?"
    answer: int
    category: str
    strategy: str      # stable ID — stats key on it, never rename
    difficulty: int    # 1–3
    hints: list[str]   # [nudge toward the pattern, explicit transformation]
    steps: list[str]   # worked method, every line "<sum> = <result>"
