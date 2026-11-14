"""At most two tracked retrievals, with explicit job identities and no retries."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait


def retrieve_jobs(jobs, retrieve, *, parallel=False, allowed=None):
    def perform(job):
        return retrieve(job['query'], job['pdfId'], limit=5)
    if not parallel:
        for job in jobs:
            yield job, perform(job)
        return
    iterator = iter(jobs)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='research-retrieval')
    pending = {}
    try:
        def fill():
            # Observe failures before admitting another tool. Every actual call
            # still uses the run's atomic budget/status/scope reservation.
            while len(pending) < 2:
                if allowed is not None and not allowed():
                    return
                for future in pending:
                    if future.done() and future.exception() is not None:
                        future.result()
                job = next(iterator, None)
                if job is None:
                    break
                pending[executor.submit(perform, job)] = job
        fill()
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            # Check all observed failures before yielding a successful result.
            results = [(future, future.result()) for future in completed]
            for future, result in results:
                yield pending.pop(future), result
            fill()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
