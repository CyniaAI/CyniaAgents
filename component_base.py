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


class PlaceholderComponent(BaseComponent):
    """Component shown when the real module failed to load."""

    def __init__(self, name: str, description: str, requirements: list[str]):
        super().__init__()
        self.name = name
        self.description = description
        self.requirements = requirements

    def render(self):
        import streamlit as st

        st.error(
            "This component could not be loaded because required libraries are missing."
        )
        if self.requirements:
            st.info(
                "Install the missing dependencies from the Component Center and restart the service to activate this component."
            )

