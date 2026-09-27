from sherlockode.analysis.base import Analyzer
from sherlockode.analysis.dependencies import DependencyAnalyzer
from sherlockode.analysis.languages import LanguageAnalyzer
from sherlockode.analysis.python_versions import PythonVersionAnalyzer


class AnalyzerRegistry:
    def __init__(self, analyzers: list[Analyzer]) -> None:
        self._analyzers = {analyzer.name: analyzer for analyzer in analyzers}

    def get(self, name: str) -> Analyzer:
        if name not in self._analyzers:
            raise KeyError(f"unknown analyzer '{name}', available: {', '.join(self._analyzers)}")
        return self._analyzers[name]

    def describe(self) -> dict[str, str]:
        return {name: analyzer.description for name, analyzer in self._analyzers.items()}


def default_analyzers() -> AnalyzerRegistry:
    return AnalyzerRegistry([LanguageAnalyzer(), PythonVersionAnalyzer(), DependencyAnalyzer()])
