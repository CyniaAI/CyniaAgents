class BaseComponent:
    """Base class for generation components."""
    name = "Unnamed"
    description = ""

    def render(self):
        """Render Streamlit UI for this component."""
        raise NotImplementedError


def get_component():
    """Dummy to satisfy loader when no component is implemented."""
    return BaseComponent()
