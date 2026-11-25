"""Finite first-order logic with capture-avoiding substitution (stdlib only).

Expressions are immutable tuples. Variables and constants have distinct tags.
A finite-model result is not a proof of logical validity.
"""
from itertools import product


def _name(name):
    if not isinstance(name, str) or not name:
        raise ValueError("expected nonempty symbol")
    return name


def var(name):
    return ("var", _name(name))


def const(name):
    return ("const", _name(name))


def func(name, *args):
    return ("func", _name(name), *args)


def pred(name, *args):
    return ("pred", _name(name), *args)


def _children(expr):
    tag = expr[0]
    if tag in ("var", "const", "true", "false"):
        return ()
    if tag in ("func", "pred", "forall", "exists"):
        return expr[2:]
    return expr[1:]


def free_variables(expr):
    """Return free variable names in a term or formula."""
    if expr[0] == "var":
        return {expr[1]}
    names = set().union(*(free_variables(c) for c in _children(expr)))
    if expr[0] in ("forall", "exists"):
        names.discard(expr[1])
    return names


def _all_variables(expr):
    names = set().union(*(_all_variables(c) for c in _children(expr)))
    if expr[0] in ("var", "forall", "exists"):
        names.add(expr[1])
    return names


def substitute(expr, name, replacement):
    """Replace only free occurrences, renaming binders when necessary."""
    tag = expr[0]
    if tag == "var":
        return replacement if expr[1] == name else expr
    if name not in free_variables(expr):
        return expr
    if tag in ("forall", "exists"):
        binder, body = expr[1:]
        if binder in free_variables(replacement):
            used = _all_variables(body) | _all_variables(replacement) | {name, binder}
            i = 0
            while f"{binder}_{i}" in used:
                i += 1
            fresh = f"{binder}_{i}"
            body = substitute(body, binder, var(fresh))
            binder = fresh
        return (tag, binder, substitute(body, name, replacement))
    offset = 2 if tag in ("func", "pred") else 1
    return (*expr[:offset], *(substitute(c, name, replacement) for c in expr[offset:]))


def universal_closure(formula):
    for name in reversed(sorted(free_variables(formula))):
        formula = ("forall", name, formula)
    return formula


def _validate(expr, term=False):
    if not isinstance(expr, tuple) or not expr:
        raise ValueError("expected expression tuple")
    tag, *args = expr
    if term:
        if tag in ("var", "const") and len(args) == 1:
            _name(args[0])
        elif tag == "func" and args:
            _name(args[0])
            for arg in args[1:]:
                _validate(arg, True)
        else:
            raise ValueError("invalid term")
    elif tag == "pred" and args:
        _name(args[0])
        for arg in args[1:]:
            _validate(arg, True)
    elif tag == "eq" and len(args) == 2:
        for arg in args:
            _validate(arg, True)
    elif tag in ("true", "false") and not args:
        return
    elif tag in ("forall", "exists") and len(args) == 2:
        _name(args[0])
        _validate(args[1])
    elif (tag == "not" and len(args) == 1 or
          tag in ("and", "or", "implies", "iff") and len(args) == 2):
        for arg in args:
            _validate(arg)
    else:
        raise ValueError("invalid formula")


class FiniteModel:
    """Explicit complete interpretations; missing symbols raise, never mean false."""

    def __init__(self, domain, *, constants=None, functions=None, predicates=None):
        self.domain = tuple(domain)
        if not self.domain:
            raise ValueError("empty domain")
        self.constants = dict(constants or {})
        self.functions = dict(functions or {})
        self.predicates = dict(predicates or {})
        for value in self.constants.values():
            self._element(value)

    def _element(self, value):
        if value not in self.domain:
            raise ValueError("value outside domain")
        return value

    def _term(self, term, env):
        tag, name, *args = term
        if tag == "var":
            return self._element(env[name])
        if tag == "const":
            return self._element(self.constants[name])
        return self._element(self.functions[name](*(self._term(a, env) for a in args)))

    def _formula(self, formula, env):
        tag, *args = formula
        if tag in ("true", "false"):
            return tag == "true"
        if tag == "pred":
            result = self.predicates[args[0]](*(self._term(a, env) for a in args[1:]))
            if type(result) is not bool:
                raise ValueError("predicate must return bool")
            return result
        if tag == "eq":
            return self._term(args[0], env) == self._term(args[1], env)
        if tag in ("forall", "exists"):
            name, body = args
            values = [self._formula(body, {**env, name: value}) for value in self.domain]
            return all(values) if tag == "forall" else any(values)
        a = self._formula(args[0], env)
        if tag == "not":
            return not a
        b = self._formula(args[1], env)
        if tag == "and":
            return a and b
        if tag == "or":
            return a or b
        if tag == "implies":
            return not a or b
        return a == b

    def evaluate(self, formula, assignment=None):
        _validate(formula)
        env = dict(assignment or {})
        for name in free_variables(formula):
            self._element(env[name])
        return self._formula(formula, env)

    def counterexample(self, formula):
        """Return a falsifying free-variable assignment, or None in this model."""
        _validate(formula)
        names = sorted(free_variables(formula))
        for values in product(self.domain, repeat=len(names)):
            env = dict(zip(names, values))
            if not self.evaluate(formula, env):
                return env
        return None
