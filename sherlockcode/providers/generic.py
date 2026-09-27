from sherlockcode.providers.base import Provider


# Plain Git hosting: every capability comes from the Git repository itself.
class GenericGitProvider(Provider):
    def owns(self, url: str) -> bool:
        return False
