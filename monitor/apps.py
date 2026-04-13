from django.apps import AppConfig


class MonitorConfig(AppConfig):
    """
    Django app configuration for the mumble monitor.
    """

    name = "monitor"
    verbose_name = "Monitor"

    def ready(self) -> None:
        """
        App is ready.
        """
        return None
