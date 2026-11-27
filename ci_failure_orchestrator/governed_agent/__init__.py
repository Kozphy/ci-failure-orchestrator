"""Fail-closed task contracts for governed autonomous code changes."""

from .contract import ContractDecision, TaskContract, validate_changes

__all__ = ["ContractDecision", "TaskContract", "validate_changes"]
