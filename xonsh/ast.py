"""The xonsh abstract syntax tree node."""
from __future__ import unicode_literals, print_function
from ast import Module, Num, Expr, Str, Bytes, UnaryOp, UAdd, USub, Invert, \
    BinOp, Add, Sub, Mult, Div, FloorDiv, Mod, Pow, Compare, Lt, Gt, LtE, \
    GtE, Eq, NotEq, In, NotIn, Is, IsNot, Not, BoolOp, Or, And, Subscript, \
    Index, Load, Slice, List, Tuple, Set, Dict, AST, NameConstant, Ellipsis, \
    Name, GeneratorExp, Store, comprehension, ListComp, SetComp, DictComp, \
    Assign, AugAssign, BitXor, BitAnd, BitOr, LShift, RShift, Assert, Delete, \
    Del, Pass, Raise, Import, alias, ImportFrom, Continue, Break, Yield, \
    YieldFrom, Return, IfExp, Lambda, arguments, arg, Call, keyword, \
    Attribute, Global, Nonlocal, If, While, For, withitem, With, Try, \
    ExceptHandler, FunctionDef, ClassDef, Starred, NodeTransformer, dump

from xonsh.tools import subproc_line

def leftmostname(node):
    """Attempts to find the first name in the tree."""
    if isinstance(node, Name):
        rtn = node.id
    elif isinstance(node, (BinOp, Compare)):
        rtn = leftmostname(node.left)
    elif isinstance(node, (Attribute, Subscript, Starred, Expr)):
        rtn = leftmostname(node.value)
    elif isinstance(node, Call):
        rtn = leftmostname(node.func)
    else:
        rtn = None
    return rtn

class CtxAwareTransformer(NodeTransformer):
    """Transforms a xonsh AST based to use subprocess calls when 
    the first name in an expression statement is not known in the context.
    This assumes that the expression statement is instead parseable as
    a subprocess.
    """

    def __init__(self, parser):
        """Parameters
        ----------
        parser : xonsh.Parser
            A parse instance to try to parse suprocess statements with.
        """
        super(CtxAwareTransformer, self).__init__()
        self.parser = parser
        self.input = None
        self.contexts = []

    def ctxvisit(self, node, input, ctx):
        """Transforms the node in a context-dependent way.

        Parameters
        ----------
        node : ast.AST
            A syntax tree to transform.
        input : str
            The input code in string format.
        ctx : dict
            The root context to use.

        Returns
        -------
        node : ast.AST
            The transformed node.
        """
        self.lines = input.splitlines()
        self.contexts = [ctx, set()]
        node = self.visit(node)
        del self.lines, self.contexts
        return node

    def ctxupdate(iterable):
        self.contexts[-1].update(iterable)
    
    def ctxadd(value):
        self.contexts[-1].add(value)

    def ctxremove(value):
        for ctx in self.contexts[::-1]:
            if value in ctx:
                ctx.remove(value)
                break

    def visit_Expr(self, node):
        lname = leftmostname(node)
        inscope = False
        for ctx in self.contexts[::-1]:
            if lname in ctx:
                inscope = True 
                break
        if inscope:
            return node
        spline = subproc_line(self.lines[node.lineno - 1])
        try:
            newnode = self.parser.parse(spline)
            newnode = newnode.body[0]  # take the first (and only) Expr
            newnode.lineno = node.lineno
            newnode.col_offset = node.col_offset
        except SyntaxError as e:
            newnode = node
        return newnode

    def visit_Assign(self, node):
        for targ in node.targets:
            if isinstance(targ, (Tuple, List)):
                self.ctxupdate(map(leftmostname, targ.elts))
            else:
                self.ctxadd(leftmostname(targ))
        return node

    def visit_Import(self, node):
        for name in node.names:
            if name.asname is None:
                self.ctxadd(name.name)
            else:
                self.ctxadd(name.asname)
        return node

    def visit_ImportFrom(self, node):
        for name in node.names:
            if name.asname is None:
                self.ctxadd(name.name)
            else:
                self.ctxadd(name.asname)
        return node

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                self.ctxadd(leftmostname(item.optional_vars))
        self.generic_visit(node)
        return node

    def visit_For(self, node):
        targ = node.target
        if isinstance(targ, (Tuple, List)):
            self.ctxupdate(map(leftmostname, targ.elts))
        else:
            self.ctxadd(leftmostname(targ))
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node):
        self.ctxadd(node.name)
        self.contexts.append(set())
        self.generic_visit(node)
        self.contexts.pop()
        return node

    def visit_ClassDef(self, node):
        self.ctxadd(node.name)
        self.contexts.append(set())
        self.generic_visit(node)
        self.contexts.pop()
        return node

    def visit_Delete(self, node):
        for targ in node.targets:
            if isinstance(targ, Name):
                self.ctxremove(targ.id)
        self.generic_visit(node)
        return node

    def visit_Try(self, node):
        for handler in node.handlers:
            if handler.name is not None:
                self.ctxadd(handler.name)
        self.generic_visit(node)
        return node

    def visit_Global(self, node):
        self.contexts[1].update(node.names)  # contexts[1] is the global ctx
        self.generic_visit(node)
        return node
