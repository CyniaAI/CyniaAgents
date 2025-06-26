from log_writer import logger as default_logger


class BaseComponent:
    """Base class for generation components."""
    name = "Unnamed"
    description = ""
    requirements: list[str] = []

    def __init__(self) -> None:
        # Provide a logger instance for all components
        self.logger = default_logger

    def render(self):
        """Render Streamlit UI for this component."""
        raise NotImplementedError


def get_component():
    """Dummy to satisfy loader when no component is implemented."""
    return BaseComponent()
