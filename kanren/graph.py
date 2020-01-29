from functools import partial

from unification import var, isvar
from unification import reify

from cons.core import ConsError

from etuples import etuple, apply, rands, rator

from .core import eq, conde, lall, goaleval, succeed, Zzz, fail
from .goals import conso, nullo


def applyo(o_rator, o_rands, obj):
    """Construct a goal that relates an object to the application of its (ope)rator to its (ope)rands.

    In other words, this is the relation `op(*args) == obj`.  It uses the
    `rator`, `rands`, and `apply` dispatch functions from `etuples`, so
    implement/override those to get the desired behavior.

    """

    def applyo_goal(S):
        nonlocal o_rator, o_rands, obj

        o_rator_rf, o_rands_rf, obj_rf = reify((o_rator, o_rands, obj), S)

        if not isvar(obj_rf):

            # We should be able to use this goal with *any* arguments, so
            # fail when the ground operations fail/err.
            try:
                obj_rator, obj_rands = rator(obj_rf), rands(obj_rf)
            except (ConsError, NotImplementedError):
                return

            # The object's rator + rands should be the same as the goal's
            yield from goaleval(
                lall(eq(o_rator_rf, obj_rator), eq(o_rands_rf, obj_rands))
            )(S)

        elif isvar(o_rands_rf) or isvar(o_rator_rf):
            # The object and at least one of the rand, rators is a logic
            # variable, so let's just assert a `cons` relationship between
            # them
            yield from goaleval(conso(o_rator_rf, o_rands_rf, obj_rf))(S)
        else:
            # The object is a logic variable, but the rator and rands aren't.
            # We assert that the object is the application of the rand and
            # rators.
            try:
                obj_applied = apply(o_rator_rf, o_rands_rf)
            except (ConsError, NotImplementedError):
                return
            yield from eq(obj_rf, obj_applied)(S)

    return applyo_goal


def mapo(relation, a, b, null_type=list, null_res=True, first=True):
    """Apply a relation to corresponding elements in two sequences and succeed if the relation succeeds for all pairs."""

    b_car, b_cdr = var(), var()
    a_car, a_cdr = var(), var()

    return conde(
        [nullo(a, b, default_ConsNull=null_type) if (not first or null_res) else fail],
        [
            conso(a_car, a_cdr, a),
            conso(b_car, b_cdr, b),
            Zzz(relation, a_car, b_car),
            Zzz(mapo, relation, a_cdr, b_cdr, null_type=null_type, first=False),
        ],
    )


def map_anyo(
    relation, a, b, null_type=list, null_res=False, first=True, any_succeed=False
):
    """Apply a relation to corresponding elements in two sequences and succeed if at least one pair succeeds.

    Parameters
    ----------
    null_type: optional
       An object that's a valid cdr for the collection type desired.  If
       `False` (i.e. the default value), the cdr will be inferred from the
       inputs, or defaults to an empty list.
    """

    b_car, b_cdr = var(), var()
    a_car, a_cdr = var(), var()

    return conde(
        [
            nullo(a, b, default_ConsNull=null_type)
            if (any_succeed or (first and null_res))
            else fail
        ],
        [
            conso(a_car, a_cdr, a),
            conso(b_car, b_cdr, b),
            conde(
                [
                    Zzz(relation, a_car, b_car),
                    Zzz(
                        map_anyo,
                        relation,
                        a_cdr,
                        b_cdr,
                        null_type=null_type,
                        any_succeed=True,
                        first=False,
                    ),
                ],
                [
                    eq(a_car, b_car),
                    Zzz(
                        map_anyo,
                        relation,
                        a_cdr,
                        b_cdr,
                        null_type=null_type,
                        any_succeed=any_succeed,
                        first=False,
                    ),
                ],
            ),
        ],
    )


def vararg_success(*args):
    return succeed


def eq_length(u, v, default_ConsNull=list):
    """Construct a goal stating that two sequences are the same length and type."""

    return mapo(vararg_success, u, v, null_type=default_ConsNull)


def reduceo(relation, in_term, out_term, *args, **kwargs):
    """Relate a term and the fixed-point of that term under a given relation.

    This includes the "identity" relation.
    """

    def reduceo_goal(s):

        nonlocal in_term, out_term, relation, args, kwargs

        in_term_rf, out_term_rf = reify((in_term, out_term), s)

        # The result of reducing the input graph once
        term_rdcd = var()

        # Are we working "backward" and (potentially) "expanding" a graph
        # (e.g. when the relation is a reduction rule)?
        is_expanding = isvar(in_term_rf)

        # One application of the relation assigned to `term_rdcd`
        single_apply_g = relation(in_term_rf, term_rdcd, *args, **kwargs)

        # Assign/equate (unify, really) the result of a single application to
        # the "output" term.
        single_res_g = eq(term_rdcd, out_term_rf)

        # Recurse into applications of the relation (well, produce a goal that
        # will do that)
        another_apply_g = reduceo(relation, term_rdcd, out_term_rf, *args, **kwargs)

        # We want the fixed-point value to show up in the stream output
        # *first*, but that requires some checks.
        if is_expanding:
            # When an un-reduced term is a logic variable (e.g. we're
            # "expanding"), we can't go depth first.
            # We need to draw the association between (i.e. unify) the reduced
            # and expanded terms ASAP, in order to produce finite
            # expanded graphs first and yield results.
            #
            # In other words, there's no fixed-point to produce in this
            # situation.  Instead, for example, we have to produce an infinite
            # stream of terms that have `out_term_rf` as a fixed point.
            # g = conde([single_res_g, single_apply_g],
            #           [another_apply_g, single_apply_g])
            g = lall(conde([single_res_g], [another_apply_g]), single_apply_g)
        else:
            # Run the recursion step first, so that we get the fixed-point as
            # the first result
            g = lall(single_apply_g, conde([another_apply_g], [single_res_g]))

        g = goaleval(g)
        yield from g(s)

    return reduceo_goal


def walko(
    goal,
    graph_in,
    graph_out,
    rator_goal=None,
    null_type=etuple,
    map_rel=partial(map_anyo, null_res=True),
):
    """Apply a binary relation between all nodes in two graphs.

    When `rator_goal` is used, the graphs are treated as term graphs, and the
    multi-functions `rator`, `rands`, and `apply` are used to walk the graphs.
    Otherwise, the graphs must be iterable according to `map_anyo`.

    Parameters
    ----------
    goal: callable
        A goal that is applied to all terms in the graph.
    graph_in: object
        The graph for which the left-hand side of a binary relation holds.
    graph_out: object
        The graph for which the right-hand side of a binary relation holds.
    rator_goal: callable (default None)
        A goal that is applied to the rators of a graph.  When specified,
        `goal` is only applied to rands and it must succeed along with the
        rator goal in order to descend into sub-terms.
    null_type: type
        The collection type used when it is not fully determined by the graph
        arguments.
    map_rel: callable
        The map relation used to apply `goal` to a sub-graph.
    """

    def walko_goal(s):

        nonlocal goal, rator_goal, graph_in, graph_out, null_type, map_rel

        graph_in_rf, graph_out_rf = reify((graph_in, graph_out), s)

        rator_in, rands_in, rator_out, rands_out = var(), var(), var(), var()

        _walko = partial(
            walko, goal, rator_goal=rator_goal, null_type=null_type, map_rel=map_rel
        )

        g = conde(
            # TODO: Use `Zzz`, if needed.
            [goal(graph_in_rf, graph_out_rf),],
            [
                lall(
                    applyo(rator_in, rands_in, graph_in_rf),
                    applyo(rator_out, rands_out, graph_out_rf),
                    rator_goal(rator_in, rator_out),
                    map_rel(_walko, rands_in, rands_out, null_type=null_type),
                )
                if rator_goal is not None
                else lall(
                    map_rel(_walko, graph_in_rf, graph_out_rf, null_type=null_type)
                ),
            ],
        )

        yield from goaleval(g)(s)

    return walko_goal
