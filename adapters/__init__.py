"""Channel adapters.

An adapter translates one transport's payload into a BrainRequest and renders a
BrainResponse back onto that transport. Translation ONLY — no business logic,
no policy decisions, no tool calls. Adding a channel means adding an adapter
here and changing nothing in bic/.
"""
