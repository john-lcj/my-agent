from core.attention_policy import AttentionAction, decide_attention


def test_attention_policy_respects_authority_and_interruption_budget():
    assert decide_attention(impact="high", authority_granted=False).action == AttentionAction.STOP
    assert decide_attention(urgency="low", authority_granted=True).action == AttentionAction.SILENT
    assert decide_attention(interruption_count=3, interruption_budget=3, authority_granted=True).action == AttentionAction.SILENT
    assert decide_attention(urgency="urgent", authority_granted=True).action == AttentionAction.EMAIL
    assert decide_attention(requires_confirmation=True, authority_granted=True).action == AttentionAction.CONFIRM
