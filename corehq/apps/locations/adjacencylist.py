from __future__ import absolute_import
from __future__ import print_function
import django
from cte_forest.models import CTENodeManager
from cte_forest.query import (
    CTECompiler,
    CTEDeleteQueryCompiler,
    CTEInsertQueryCompiler,
    CTEQuery,
    CTEUpdateQueryCompiler,
)
from django.db import connections
from django.db.models.expressions import RawSQL
from django.db.models.query import Q, QuerySet
from django.db.models.sql import AggregateQuery, DeleteQuery, InsertQuery, UpdateQuery
from django.db.models.sql.compiler import SQLAggregateCompiler, SQLCompiler
from mptt.models import MPTTModel


class ALManager(CTENodeManager):

    def get_ancestors(self, node, include_self=False):
        """Query node ancestors

        :param node: A model instance or a QuerySet or Q object querying
        the adjacency list model. If a QuerySet, it should query a single
        value with something like `.values('pk')`.
        :returns: A `QuerySet` instance.
        """
        self._ensure_parameters()
        if include_self:
            offset = node
        else:
            if isinstance(node, QuerySet):
                # maybe need to adjust this to support subqueries that do
                # not have a parent_id field (e.g., if using GROUP BY)
                offset = node.values(node._cte_node_parent_attname)
            else:
                offset = Q(pk=getattr(node, node._cte_node_parent_attname))
        offset = AncestorOffset(offset)
        return ALQuerySet(self.model, using=self._db, offset=offset)

    def get_descendants(self, node, include_self=False):
        """Query node descendants

        :param node: A model instance or a QuerySet or Q object querying
        the adjacency list model.
        :returns: A `QuerySet` instance.
        """
        self._ensure_parameters()
        if include_self:
            offset = node
        else:
            if isinstance(node, QuerySet):
                offset = node.model.filter(**{
                    node._cte_node_parent_attname + "__in": node
                }).values('pk')
            else:
                offset = Q(**{node._cte_node_parent_attname: node.id})
        return ALQuerySet(self.model, using=self._db, offset=offset)

    get_queryset_ancestors = get_ancestors
    get_queryset_descendants = get_descendants


class ALModel(MPTTModel):
    """Base class for tree models implemented with adjacency list pattern

    For more on adjacency lists, see
    https://explainextended.com/2009/09/24/adjacency-list-vs-nested-sets-postgresql/
    """

    _cte_node_parent = 'parent'

    objects = ALManager()

    class Meta:
        abstract = True

    def get_children(self):
        return self.children

    def get_ancestors(self, ascending=False, include_self=False):
        # TODO handle ascending
        return type(self).objects.get_ancestors(self, include_self)

    def get_descendants(self, include_self=False):
        return type(self).objects.get_descendants(self, include_self)


class ALCompiler(CTECompiler):
    # NOTE the "depth" and "path" dynamic columns do not have the same
    # meaning here as in CTECompiler because the WHERE condition is not
    # bound to the root of the tree: they are calculated from the
    # node(s) being queried in the adjacency list WHERE condition.
    # "path" has the opposite meaning for ancestor queries as it does
    # for descendants.

    ADJACENCY_LIST_SQL = """
    WITH RECURSIVE {cte} ("{pk}", "{path}", "{depth}", "{ordering}") AS (
        %(base_sql)s
        UNION ALL
        SELECT
            T."{pk}",
            {cte}.{path} || {pk_path},
            {cte}.{depth} %(depth_op)s 1,
            {cte}.{ordering} || {order}
        FROM {db_table} T
        JOIN {cte} ON %(cte_join_on)s
    )
    """

    @classmethod
    def generate_sql(cls, connection, query, as_sql):
        frags, cte_params = compile_adjancency_list_query(query, connection)
        cte = cls.ADJACENCY_LIST_SQL % frags
        compiler = type("DynamicALCompiler", (CTECompiler,), {"CTE": cte})
        sql, params = compiler.generate_sql(connection, query, as_sql)
        # possibly fragile: concatenate cte_params with params
        return sql, cte_params + params


def compile_adjancency_list_query(query, connection):
    offset = query._adjancency_list_offset
    if isinstance(offset, AncestorOffset):
        cte_join_on = 'T."{pk}" = {cte}."{parent}"'
        offset = offset.value
        depth_op = '-'
    else:
        cte_join_on = 'T."{parent}" = {cte}."{pk}"'
        depth_op = '+'

    # SELECT "{pk}", array[{pk_path}] AS "path", 0 AS "depth", {order}
    # FROM {db_table}
    # WHERE ...
    pk_path, order = get_pk_path_and_order(query, connection)
    base_query = query.model.objects.annotate(**{
        query.model._cte_node_path: RawSQL('array[%s]' % pk_path, []),
    }).annotate(**{
        query.model._cte_node_depth: RawSQL('0', []),
    }).annotate(**{
        query.model._cte_node_ordering: RawSQL(order, []),
    }).values(
        'pk',
        query.model._cte_node_path,
        query.model._cte_node_depth,
        query.model._cte_node_ordering,
    )
    if isinstance(offset, QuerySet):
        assert issubclass(offset.query.model, query.model), \
            "expected offset to be {}, but got {}".format(
                query.model.__name__,
                offset.query.model.__name__,
            )  # noqa
        base_query = base_query.filter(pk__in=offset)
    elif isinstance(offset, Q):
        base_query = base_query.filter(offset)
    elif isinstance(offset, query.model):
        base_query = base_query.filter(pk=offset.id)
    else:
        raise ValueError("bad offset: {!r}".format(offset))

    base_compiler = base_query.query.get_compiler(connection=connection)
    base_sql, cte_params = base_compiler.as_sql()
    query_fragments = {
        "base_sql": base_sql,
        "depth_op": depth_op,
        "cte_join_on": cte_join_on,
    }
    return query_fragments, cte_params


class AncestorOffset(object):
    """Marker class to signal ancestor query"""

    def __init__(self, value):
        self.value = value


def get_pk_path_and_order(query, connection):
    """This code was copied from django-cte-forest and slightly modified

    Changed table alias used in `maybe_cast` to be the real table name.

    Source:
    https://github.com/matthiask/django-cte-forest/blob/0.2.2/cte_forest/query.py#L355-L401
    """
    table_name = query.model._meta.db_table

    def maybe_cast(field):
        # If the ordering information specified a type to cast to, then use
        # this type immediately, otherwise determine whether a
        # variable-length character field should be cast into TEXT or if no
        # casting is necessary. A None type defaults to the latter.
        if type(field) == tuple and not field[1] is None:
            return 'CAST ("%s"."%s" AS %s)' % ((table_name,) + field)
        else:
            if type(field) == tuple:
                name = field[0]
            else:
                name = field
            _field = query.model._meta.get_field(name)
            if _field.db_type(connection).startswith('varchar'):
                return 'CAST ("%s"."%s" AS TEXT)' % (table_name, name)
            else:
                return '"%s"."%s"' % (table_name, name)

    # The primary key is used in the path; in case it is of a custom type,
    # ensure appropriate casting is performed. This is a very rare
    # condition, as most types can be used directly in the path, especially
    # since no other fields with incompatible types are combined (with a
    # notable exception of VARCHAR types which must be converted to TEXT).
    pk_path = maybe_cast((query.model._meta.pk.attname,
                          query.model._cte_node_primary_key_type))

    # If no explicit ordering is specified, then use the primary key. If the
    # primary key is used in ordering, and it is of a type which needs
    # casting in order to be used in the ordering, then it is possible that
    # explicit casting was not specified through _cte_node_order_by because
    # it is expected to be specified through the _cte_node_primary_key_type
    # attribute. Specifying the cast type of the primary key in the
    # _cte_node_order_by attribute has precedence over
    # _cte_node_primary_key_type.
    if not hasattr(query.model, '_cte_node_order_by') or \
            query.model._cte_node_order_by is None or \
            len(query.model._cte_node_order_by) == 0:
        order = 'array[%s]' % maybe_cast((
            query.model._meta.pk.attname,
            query.model._cte_node_primary_key_type))
    else:
        # Compute the ordering virtual field constructor, possibly casting
        # fields into a common type.
        order = '||'.join(
            'array[%s]' % maybe_cast(field)
            for field in query.model._cte_node_order_by
        )
    return pk_path, order


# all code below facilitates extending CTECompiler to use different SQL


class ALQuerySet(QuerySet):

    def __init__(self, model=None, query=None, using=None, offset=None, hints=None):
        """
        Prepares an ALQuery object by adding appropriate extras, namely the
        SELECT virtual fields, the WHERE clause which matches the CTE pk with
        the real table pk, and the tree-specific order_by parameters. If the
        query object has already been prepared through this phase, then it
        won't be prepared again.
        """
        # Only create an instance of a Query if this is the first invocation in
        # a query chain.
        if query is None and offset is not None:
            query = ALQuery(model)
            query._adjancency_list_offset = offset
        super(ALQuerySet, self).__init__(model, query, using, hints)

    def aggregate(self, *args, **kwargs):
        """
        Returns a dictionary containing the calculations (aggregation)
        over the current queryset
        If args is present the expression is passed as a kwarg using
        the Aggregate object's default alias.
        """
        if self.query.distinct_fields:
            raise NotImplementedError("aggregate() + distinct(fields) not implemented.")
        for arg in args:
            # The default_alias property may raise a TypeError, so we use
            # a try/except construct rather than hasattr in order to remain
            # consistent between PY2 and PY3 (hasattr would swallow
            # the TypeError on PY2).
            try:
                arg.default_alias
            except (AttributeError, TypeError):
                raise TypeError("Complex aggregates require an alias")
            kwargs[arg.default_alias] = arg

        if django.VERSION < (2, 0):
            query = self.query.clone(ALAggregateQuery)
        else:
            query = self.query.chain(ALAggregateQuery)
        for (alias, aggregate_expr) in kwargs.items():
            query.add_annotation(aggregate_expr, alias, is_summary=True)
            if not query.annotations[alias].contains_aggregate:
                raise TypeError("%s is not an aggregate expression" % alias)
        return query.get_aggregation(self.db, kwargs.keys())


class ALQuery(CTEQuery):

    _adjancency_list_offset = None

    def get_compiler(self, using=None, connection=None):
        """ Overrides the Query method get_compiler in order to return
            an instance of the above custom compiler.
        """
        # Copy the body of this method from Django except the final
        # return statement. We will ignore code coverage for this.
        if using is None and connection is None:  # pragma: no cover
            raise ValueError("Need either using or connection")
        if using:
            connection = connections[using]
        # Check that the compiler will be able to execute the query
        for alias, aggregate in self.annotation_select.items():
            connection.ops.check_expression_support(aggregate)
        # Instantiate the custom compiler.
        return {
            ALUpdateQuery: CTEUpdateQueryCompiler,
            ALInsertQuery: CTEInsertQueryCompiler,
            ALDeleteQuery: CTEDeleteQueryCompiler,
            ALAggregateQuery: ALAggregateQueryCompiler,
        }.get(self.__class__, ALQueryCompiler)(self, connection, using)

    if django.VERSION < (2, 0):
        def clone(self, klass=None, memo=None, **kwargs):
            """ Overrides Django's Query clone in order to return appropriate CTE
                compiler based on the target Query class. This mechanism is used by
                methods such as 'update' and '_update' in order to generate UPDATE
                queries rather than SELECT queries.
            """
            klass = {
                UpdateQuery: ALUpdateQuery,
                InsertQuery: ALInsertQuery,
                DeleteQuery: ALDeleteQuery,
                AggregateQuery: ALAggregateQuery,
            }.get(klass, self.__class__)
            obj = super(ALQuery, self).clone(klass, memo, **kwargs)
            obj._adjancency_list_offset = self._adjancency_list_offset
            return obj

    else:
        def chain(self, klass=None):
            """ Overrides Django's Query clone in order to return appropriate CTE
                compiler based on the target Query class. This mechanism is used by
                methods such as 'update' and '_update' in order to generate UPDATE
                queries rather than SELECT queries.
            """
            klass = {
                UpdateQuery: ALUpdateQuery,
                InsertQuery: ALInsertQuery,
                DeleteQuery: ALDeleteQuery,
                AggregateQuery: ALAggregateQuery,
            }.get(klass, self.__class__)
            obj = super(ALQuery, self).chain(klass)
            obj._adjancency_list_offset = self._adjancency_list_offset
            return obj


class ALUpdateQuery(UpdateQuery, ALQuery):
    pass


class ALInsertQuery(InsertQuery, ALQuery):
    pass


class ALDeleteQuery(DeleteQuery, ALQuery):
    pass


class ALAggregateQuery(AggregateQuery, ALQuery):
    pass


class ALQueryCompiler(SQLCompiler):

    def as_sql(self, *args, **kwargs):
        def _as_sql():
            return super(ALQueryCompiler, self).as_sql(*args, **kwargs)
        return ALCompiler.generate_sql(self.connection, self.query, _as_sql)


class ALAggregateQueryCompiler(SQLAggregateCompiler):

    def as_sql(self, *args, **kwargs):
        def _as_sql():
            return super(ALAggregateQueryCompiler, self).as_sql(*args, **kwargs)
        return ALCompiler.generate_sql(self.connection, self.query, _as_sql)
