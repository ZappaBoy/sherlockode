from collections import Counter

from sherlockcode.analysis.base import AnalysisTarget, Analyzer, AnalyzerReport
from sherlockcode.domain.evidence import EvidenceDraft, EvidenceKind, EvidenceSource, SourceKind

EXTENSIONS = {
    ".py": "Python",
    ".pyi": "Python",
    ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".scala": "Scala",
    ".groovy": "Groovy",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".fs": "F#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".clj": "Clojure",
    ".hs": "Haskell",
    ".lua": "Lua",
    ".r": "R",
    ".jl": "Julia",
    ".pl": "Perl",
    ".sh": "Shell",
    ".bash": "Shell",
    ".ps1": "PowerShell",
    ".tf": "HCL",
    ".sql": "SQL",
    ".vue": "Vue",
    ".svelte": "Svelte",
}


class LanguageAnalyzer(Analyzer):
    name = "languages"
    description = "Counts tracked source files per programming language, based on file extensions."

    def analyze(self, target: AnalysisTarget) -> AnalyzerReport:
        counts = Counter(
            language for path in target.files if (language := EXTENSIONS.get(_extension(path))) is not None
        )
        ranking = dict(counts.most_common())
        primary = next(iter(ranking), None)
        evidence = EvidenceDraft(
            kind=EvidenceKind.COMPUTED,
            statement=f"{target.repository.name}: source files per language {ranking}",
            source=EvidenceSource(
                kind=SourceKind.ANALYZER,
                repository=target.repository.name,
                commit=target.commit,
                command="git ls-files | classify by extension",
            ),
        )
        return self.report(target, {"primary_language": primary, "files_per_language": ranking}, [evidence])


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[name.rfind(".") :].lower() if "." in name else ""
