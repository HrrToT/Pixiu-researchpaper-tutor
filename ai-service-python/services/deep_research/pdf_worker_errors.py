"""Safe parser error categories; document text and exception messages never leave worker."""
import re

PREFIX='PIXIU_PDF_PARSE_ERROR:'
KINDS=frozenset({'PdfReadError','PdfStreamError','DependencyError','ValueError','OSError',
    'KeyError','IndexError','TypeError','RecursionError','MemoryError','ImportError',
    'ModuleNotFoundError','UnicodeDecodeError','UnicodeEncodeError','ParserError'})


def encode_failure(error):
    kind=type(error).__name__
    return PREFIX+(kind if kind in KINDS else 'ParserError')+'\n'


def details(process):
    stderr=process.stderr if isinstance(process.stderr,bytes) else b''
    tags=re.findall(rb'(?m)^PIXIU_PDF_PARSE_ERROR:([A-Za-z]+)\r?$',stderr[:8192])
    kind=tags[0].decode('ascii') if len(tags)==1 else None
    if kind not in KINDS:kind='worker_exit'
    return {'workerExitCode':process.returncode,'workerFailureKind':kind}
