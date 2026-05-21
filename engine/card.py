from dataclasses import dataclass
from core.constants import SUIT_TO_SYMBOL, SUIT_COLOR, RANK_ORDER
from core.utils import split_card_code

@dataclass(frozen=True)
class Card:
    rank: str   # '2'..'9','T','J','Q','K','A'
    suit: str   # 'R','C','B','T'

    @classmethod
    def from_code(cls, code: str) -> "Card":
        rank, suit = split_card_code(code)
        return cls(rank=rank, suit=suit)

    @property
    def rank_index(self) -> int:
        return RANK_ORDER.index(self.rank)

    def display(self) -> str:
        symbol = SUIT_TO_SYMBOL.get(self.suit, "?")
        return f"{self.rank}{symbol}"

    @property
    def color(self) -> str:
        return SUIT_COLOR.get(self.suit, "black")

    def to_code(self) -> str:
        return f"{self.rank}{self.suit}"

    @property
    def code(self) -> str:
        """Compatibility: return compact code like 'AR', '9C'."""
        return self.to_code()
