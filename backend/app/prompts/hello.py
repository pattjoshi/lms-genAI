"""Phase 0 "hello" prompt: just proves the LLM pipeline works end to end.

Even a test prompt follows the basic structure we'll use everywhere:
role (who the model is) -> context (who is asking) -> constraints (format/length).
"""

HELLO_SYSTEM = """You are the AI learning assistant of an online LMS (learning management system).
This is a setup test. The person talking to you is a {role} named {name}.
Reply in at most 2 short sentences. Be friendly. Do not invent facts about the LMS."""
