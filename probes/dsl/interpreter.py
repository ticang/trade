"""Minimal DSL interpreter: func(arg, arg, ...) where args are field names, ints, or nested calls."""
import re
import pandas as pd
from probes.dsl import operators as ops

_TOKEN = re.compile(r"\s*(?:(?P<num>\d+)|(?P<name>[A-Za-z_]\w*)|(?P<lp>\()|(?P<rp>\))|(?P<comma>,))")

def _tokenize(s: str):
    pos = 0
    tokens = []
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            raise ValueError(f"bad token at {s[pos:]!r}")
        pos = m.end()
        for k in ("num", "name", "lp", "rp", "comma"):
            if m.group(k) is not None:
                tokens.append((k, m.group(k)))
    return tokens

def _parse(tokens):
    # Recursive descent: expr := name '(' args ')' | name | num
    pos = 0
    def parse_expr():
        nonlocal pos
        kind, val = tokens[pos]
        if kind == "num":
            pos += 1
            return ("num", int(val))
        if kind == "name":
            pos += 1
            if pos < len(tokens) and tokens[pos][0] == "lp":
                pos += 1  # consume '('
                args = []
                if tokens[pos][0] != "rp":
                    args.append(parse_expr())
                    while tokens[pos][0] == "comma":
                        pos += 1
                        args.append(parse_expr())
                assert tokens[pos][0] == "rp", "expected )"
                pos += 1
                return ("call", val, args)
            return ("field", val)
        raise ValueError(f"unexpected token {kind}")

    ast = parse_expr()
    assert pos == len(tokens), "trailing tokens"
    return ast

def _eval(node, df: pd.DataFrame) -> pd.Series:
    kind = node[0]
    if kind == "field":
        return df[node[1]]
    if kind == "num":
        return node[1]
    if kind == "call":
        _, fname, args = node
        evaluated = [_eval(a, df) for a in args]
        if fname == "ts_mean":
            field_ref, window = args[0], evaluated[1]
            assert field_ref[0] == "field"
            return ops.ts_mean(df, field_ref[1], window)
        if fname == "rank":
            return ops.rank(df, evaluated[0])
        if fname == "group_neutral":
            group_ref = args[1]
            assert group_ref[0] == "field"
            return ops.group_neutral(df, evaluated[0], group_ref[1])
        raise ValueError(f"unknown operator {fname}")
    raise ValueError(f"bad node {node}")

def evaluate(expr: str, df: pd.DataFrame) -> pd.Series:
    """Evaluate a DSL expression over a long-form panel; returns the last cross-section (Series indexed by symbol)."""
    ast = _parse(_tokenize(expr))
    full = _eval(ast, df)
    if isinstance(full, pd.Series):
        full = full.copy()
        full.index = df.index
        df = df.assign(__result=full.values)
        last_day = df["trade_date"].max()
        out = df[df.trade_date == last_day].set_index("symbol")["__result"]
        return out
    raise ValueError("expression did not yield a series")
