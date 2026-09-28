from .compliance import COMPLIANCE_TOOLS
from .documents import DOCUMENT_TOOLS
from .files import FILE_TOOLS
from .workbench import WORKBENCH_TOOLS

ALL_TOOLS = [*FILE_TOOLS, *DOCUMENT_TOOLS, *COMPLIANCE_TOOLS, *WORKBENCH_TOOLS]

__all__ = ["ALL_TOOLS"]
