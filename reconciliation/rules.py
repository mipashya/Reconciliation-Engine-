"""Rules Engine for Reconciliation

Supports flexible rule definitions with AND/OR logic composition,
priority-based rule evaluation, and audit trail tracking.
"""
import logging
from typing import Dict, List, Tuple, Callable, Optional, Any
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from datetime import date

logger = logging.getLogger(__name__)


class RuleOperator(Enum):
    """Rule logic operators"""
    AND = 'AND'
    OR = 'OR'


class RuleComparison(Enum):
    """Comparison operators for rule conditions"""
    EQUALS = 'equals'
    NOT_EQUALS = 'not_equals'
    GREATER_THAN = 'greater_than'
    LESS_THAN = 'less_than'
    CONTAINS = 'contains'
    STARTS_WITH = 'starts_with'
    WITHIN_TOLERANCE = 'within_tolerance'
    DATE_WITHIN = 'date_within'


@dataclass
class RuleCondition:
    """Individual rule condition"""
    field: str
    comparison: RuleComparison
    value: Any
    weight: float = 1.0

    def evaluate(self, transaction: Dict) -> Tuple[bool, float]:
        """
        Evaluate condition against transaction.
        
        Args:
            transaction: Transaction dictionary
            
        Returns:
            Tuple of (passed: bool, confidence: float)
        """
        transaction_value = transaction.get(self.field)
        
        if transaction_value is None:
            return False, 0.0

        try:
            if self.comparison == RuleComparison.EQUALS:
                passed = transaction_value == self.value
                confidence = 1.0 if passed else 0.0

            elif self.comparison == RuleComparison.NOT_EQUALS:
                passed = transaction_value != self.value
                confidence = 1.0 if passed else 0.0

            elif self.comparison == RuleComparison.GREATER_THAN:
                passed = Decimal(str(transaction_value)) > Decimal(str(self.value))
                confidence = 1.0 if passed else 0.0

            elif self.comparison == RuleComparison.LESS_THAN:
                passed = Decimal(str(transaction_value)) < Decimal(str(self.value))
                confidence = 1.0 if passed else 0.0

            elif self.comparison == RuleComparison.CONTAINS:
                passed = str(self.value).lower() in str(transaction_value).lower()
                confidence = 1.0 if passed else 0.0

            elif self.comparison == RuleComparison.STARTS_WITH:
                passed = str(transaction_value).lower().startswith(str(self.value).lower())
                confidence = 1.0 if passed else 0.0

            elif self.comparison == RuleComparison.WITHIN_TOLERANCE:
                tolerance = self.value
                diff = abs(Decimal(str(transaction_value)) - Decimal(str(self.value)))
                passed = diff <= Decimal(str(tolerance))
                confidence = 1.0 - float(diff) / (float(tolerance) + 1) if passed else 0.0

            elif self.comparison == RuleComparison.DATE_WITHIN:
                days_tolerance = self.value
                if isinstance(transaction_value, date) and isinstance(self.value, date):
                    diff_days = abs((transaction_value - self.value).days)
                    passed = diff_days <= days_tolerance
                    confidence = 1.0 - (diff_days / (days_tolerance + 1)) if passed else 0.0
                else:
                    passed = False
                    confidence = 0.0
            else:
                passed = False
                confidence = 0.0

            return passed, confidence * self.weight

        except (ValueError, TypeError) as e:
            logger.warning(f"Error evaluating condition: {e}")
            return False, 0.0


@dataclass
class Rule:
    """Reconciliation rule with conditions and metadata"""
    id: str
    name: str
    conditions: List[RuleCondition]
    operator: RuleOperator = RuleOperator.AND
    priority: int = 100
    enabled: bool = True
    description: str = ""
    
    def evaluate(self, source: Dict, target: Dict) -> Tuple[bool, float, str]:
        """
        Evaluate rule against transaction pair.
        
        Args:
            source: Source transaction
            target: Target transaction
            
        Returns:
            Tuple of (matched: bool, confidence: float, explanation: str)
        """
        if not self.enabled or not self.conditions:
            return False, 0.0, "Rule disabled or has no conditions"

        condition_results = []
        explanations = []

        for condition in self.conditions:
            # Try condition on source
            source_passed, source_conf = condition.evaluate(source)
            # Try condition on target
            target_passed, target_conf = condition.evaluate(target)
            
            # Use best result
            if source_passed and target_passed:
                passed = True
                confidence = max(source_conf, target_conf)
            else:
                passed = source_passed or target_passed
                confidence = max(source_conf, target_conf)
            
            condition_results.append(passed)
            explanations.append(
                f"{condition.field} {condition.comparison.value}: {passed} "
                f"(confidence: {confidence:.2f})"
            )

        # Apply operator logic
        if self.operator == RuleOperator.AND:
            matched = all(condition_results) if condition_results else False
            avg_confidence = (
                sum(r[1] for r in [
                    self.conditions[i].evaluate(source) if condition_results[i] else (False, 0.0)
                    for i in range(len(self.conditions))
                ]) / len(self.conditions)
                if condition_results else 0.0
            )
        else:  # OR
            matched = any(condition_results) if condition_results else False
            avg_confidence = (
                max(r[1] for r in [
                    self.conditions[i].evaluate(source) 
                    for i in range(len(self.conditions))
                ]) if condition_results else 0.0
            )

        explanation = f"Rule '{self.name}': {self.operator.value} - {', '.join(explanations)}"
        
        return matched, avg_confidence, explanation


class RulesEngine:
    """Rules engine for reconciliation matching
    
    Manages rule definitions, evaluation, and priority-based matching.
    """

    def __init__(self):
        """Initialize RulesEngine"""
        self.rules: Dict[str, Rule] = {}
        self.evaluation_history: List[Dict] = []

    def add_rule(self, rule: Rule) -> None:
        """
        Add rule to engine.
        
        Args:
            rule: Rule to add
        """
        self.rules[rule.id] = rule
        logger.info(f"Rule '{rule.name}' added with priority {rule.priority}")

    def remove_rule(self, rule_id: str) -> None:
        """
        Remove rule from engine.
        
        Args:
            rule_id: ID of rule to remove
        """
        if rule_id in self.rules:
            del self.rules[rule_id]
            logger.info(f"Rule '{rule_id}' removed")

    def get_rules_by_priority(self) -> List[Rule]:
        """
        Get rules sorted by priority (lower number = higher priority).
        
        Returns:
            List of rules sorted by priority
        """
        return sorted(self.rules.values(), key=lambda r: r.priority)

    def evaluate_all(self, source: Dict, target: Dict) -> Tuple[bool, float, str, str]:
        """
        Evaluate all rules against transaction pair in priority order.
        
        Args:
            source: Source transaction
            target: Target transaction
            
        Returns:
            Tuple of (matched: bool, confidence: float, explanation: str, matched_rule_id: str)
        """
        sorted_rules = self.get_rules_by_priority()
        
        for rule in sorted_rules:
            matched, confidence, explanation = rule.evaluate(source, target)
            
            # Record evaluation
            self.evaluation_history.append({
                'rule_id': rule.id,
                'matched': matched,
                'confidence': confidence,
                'explanation': explanation
            })
            
            if matched:
                logger.debug(
                    f"Match found by rule '{rule.name}' with confidence {confidence:.2f}"
                )
                return True, confidence, explanation, rule.id

        return False, 0.0, "No matching rules", ""

    def evaluate_specific(self, rule_id: str, source: Dict, target: Dict) -> Tuple[bool, float, str]:
        """
        Evaluate specific rule against transaction pair.
        
        Args:
            rule_id: ID of rule to evaluate
            source: Source transaction
            target: Target transaction
            
        Returns:
            Tuple of (matched: bool, confidence: float, explanation: str)
        """
        if rule_id not in self.rules:
            return False, 0.0, f"Rule '{rule_id}' not found"

        rule = self.rules[rule_id]
        matched, confidence, explanation = rule.evaluate(source, target)
        
        self.evaluation_history.append({
            'rule_id': rule_id,
            'matched': matched,
            'confidence': confidence,
            'explanation': explanation
        })
        
        return matched, confidence, explanation

    def get_evaluation_history(self) -> List[Dict]:
        """
        Get evaluation history.
        
        Returns:
            List of evaluation records
        """
        return self.evaluation_history.copy()

    def clear_history(self) -> None:
        """Clear evaluation history"""
        self.evaluation_history.clear()

    def create_rule(
        self,
        rule_id: str,
        name: str,
        conditions: List[RuleCondition],
        operator: RuleOperator = RuleOperator.AND,
        priority: int = 100,
        description: str = ""
    ) -> Rule:
        """
        Create and add a rule to the engine.
        
        Args:
            rule_id: Unique rule identifier
            name: Human-readable rule name
            conditions: List of conditions
            operator: AND or OR logic
            priority: Priority number (lower = higher priority)
            description: Rule description
            
        Returns:
            Created Rule object
        """
        rule = Rule(
            id=rule_id,
            name=name,
            conditions=conditions,
            operator=operator,
            priority=priority,
            description=description
        )
        self.add_rule(rule)
        return rule
