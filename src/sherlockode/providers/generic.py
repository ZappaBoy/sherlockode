from sherlockode.providers.base import Provider


class GenericGitProvider(Provider):
    """Plain Git hosting: every capability comes from the Git repository itself."""

    def owns(self, url: str) -> bool:
        return False
