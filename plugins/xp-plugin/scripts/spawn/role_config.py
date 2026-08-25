from work import config_block_value


def card_role(card: str, role: str) -> str:
    label = f"{role.capitalize()}:"
    for line in card.splitlines():
        if line.startswith(label):
            value = line.removeprefix(label).strip()
            return "" if value == "(default)" else value
    return ""


def config_role(role: str, missing: str = "") -> str:
    return config_block_value("roles", role, missing)
