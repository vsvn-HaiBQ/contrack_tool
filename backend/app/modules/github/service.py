def build_pr_title(base_branch: str, jp_tickets: list[int], subjects: list[str]) -> str:
    if len(jp_tickets) == 1:
        return f"{base_branch} (#{jp_tickets[0]}) {subjects[0]}"
    joined = ", ".join(f"#{ticket}" for ticket in jp_tickets[:2])
    return f"{base_branch} ({joined})"


def build_pr_body(jp_tickets: list[int], source_branch: str) -> str:
    ticket_lines = "\n".join(f"- JP {ticket}" for ticket in jp_tickets)
    return f"## Summary\n- source branch: {source_branch}\n\n## Tickets\n{ticket_lines}\n"
