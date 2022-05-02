import re
import typing as T

class Filter:
    def __init__(self, files):
        self._filter_codes = []
        for file in files:
            with open(file, "r") as f:
                self._filter_codes += (
                    line.strip()
                    for line in f
                    if not line.isspace() and not line.startswith("#")
                )

        self._filters = [_create_filter(code) for code in self._filter_codes]

    def __call__(self, string: str) -> str:
        for filter in self._filters:
            string = filter(string)
        return string

    def __getstate__(self):
        return self._filter_codes

    def __setstate__(self, state):
        self._filter_codes = state
        self._filters = [_create_filter(code) for code in self._filter_codes]


def _create_filter(filter: str) -> T.Callable[[str], str]:
    match filter:
        case "title_case":
            return str.title
        case _:
            segments = filter.split(" => ")
            if len(segments) != 2:
                raise Exception(f"invalid filter: {filter}")
            regex_code, replace = segments
            regex = re.compile(regex_code, re.IGNORECASE)

            def func(string: str):
                return regex.sub(replace, string)

            return func
