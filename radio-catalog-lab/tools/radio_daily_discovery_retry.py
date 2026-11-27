"""Durable bounded Radio Browser page retry queue, never admission evidence."""
import datetime as dt
import re

MAX_PENDING = 512
MAX_RETRIES = 4
MAX_ATTEMPTS = 20


def key(row):
    return row["field"], row["term"], row["offset"], row["pageSize"]


def safe_key(k):
    field, term, offset, size = k
    return (field in ("tag","name") and isinstance(term,str)
            and 1 <= len(term) <= 60 and term == term.strip()
            and re.fullmatch(r"[\w !&+/\-]+",term,re.UNICODE)
            and type(size) is int and 1 <= size <= 250
            and type(offset) is int and 0 <= offset <= 35000 and offset % size == 0)


def date(value):
    parsed = dt.date.fromisoformat(value)
    if parsed.isoformat()!=value:
        raise ValueError("noncanonical retry date")
    return parsed


def load(state, day):
    if state is None:
        return {}
    if (not isinstance(state,dict) or set(state)!={"schemaVersion","publicationAllowed","scanDate","pending"}
            or state["schemaVersion"]!=1 or state["publicationAllowed"] is not False
            or date(state["scanDate"])>day or not isinstance(state["pending"],list)
            or len(state["pending"])>MAX_PENDING):
        raise ValueError("invalid discovery retry state")
    result={}
    for row in state["pending"]:
        if not isinstance(row,dict) or set(row)!={"field","term","offset","pageSize",
                "firstFailureDate","lastAttemptDate","attemptCount","nextAttemptDate"}:
            raise ValueError("invalid retry row")
        k=key(row)
        if not safe_key(k) or k in result:
            raise ValueError("invalid retry identity")
        first,last,next_day=map(date,(row["firstFailureDate"],row["lastAttemptDate"],row["nextAttemptDate"]))
        if (not first<=last<=date(state["scanDate"])<=day
                or not last<next_day<=last+dt.timedelta(days=7)
                or type(row["attemptCount"]) is not int or not 1<=row["attemptCount"]<=MAX_ATTEMPTS):
            raise ValueError("invalid retry history")
        result[k]=dict(row)
    return result


def failed(pending,k,day):
    if not safe_key(k):
        raise ValueError("unsafe retry query")
    old=pending.get(k)
    # Multiple scans on the same day cannot accelerate backoff.
    if old and old["lastAttemptDate"]==day.isoformat():
        return
    attempts=min(MAX_ATTEMPTS,(old["attemptCount"] if old else 0)+1)
    delay=min(7,2**min(attempts-1,3))
    field,term,offset,size=k
    pending[k]=dict(field=field,term=term,offset=offset,pageSize=size,
        firstFailureDate=old["firstFailureDate"] if old else day.isoformat(),
        lastAttemptDate=day.isoformat(),attemptCount=attempts,
        nextAttemptDate=(day+dt.timedelta(days=delay)).isoformat())
    if len(pending)>MAX_PENDING:
        raise ValueError("discovery retry queue capacity exceeded")


def due(pending,day,attempted):
    eligible=[(k,r) for k,r in pending.items()
        if k not in attempted and date(r["nextAttemptDate"])<=day]
    eligible.sort(key=lambda item:(item[1]["nextAttemptDate"],item[1]["firstFailureDate"],item[0]))
    return [k for k,_ in eligible[:MAX_RETRIES]]


def report(pending,day):
    return dict(schemaVersion=1,publicationAllowed=False,scanDate=day.isoformat(),
                pending=[pending[k] for k in sorted(pending)])
