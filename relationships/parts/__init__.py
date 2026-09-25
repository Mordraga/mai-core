from relationships.parts.familiar import Familiar
from relationships.parts.bond import Bond
from relationships.parts.desire import Desire
from relationships.parts.tease import Tease
from relationships.parts.curiosity import Curiosity
from relationships.parts.crash import Crash

ALL_PARTS = [Familiar(), Bond(), Desire(), Tease(), Curiosity(), Crash()]

__all__ = ["ALL_PARTS", "Familiar", "Bond", "Desire", "Tease", "Curiosity", "Crash"]
