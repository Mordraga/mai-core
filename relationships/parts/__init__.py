"""Mai's Parts — competing psychological impulses, script-based.

Each module here defines one small class with a react() method that reads
relationship/needs state directly and returns a categorical PartVote. This
mirrors selyros-beta's brain/conscious/parts pattern (chessie.py, moira.py,
solace.py, part_core.py) rather than a generic scored/thresholded data
system: each Part decides its own vote with its own logic, and PartCore
(see partcore.py) arbitrates with a short hardcoded precedence chain.
"""
from relationships.parts.bond import Bond
from relationships.parts.crash import Crash
from relationships.parts.curiosity import Curiosity
from relationships.parts.desire import Desire
from relationships.parts.familiar import Familiar
from relationships.parts.tease import Tease

ALL_PARTS = [Crash(), Desire(), Bond(), Tease(), Curiosity(), Familiar()]

__all__ = ["Bond", "Crash", "Curiosity", "Desire", "Familiar", "Tease", "ALL_PARTS"]
