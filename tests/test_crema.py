import io
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crema import VM, CremaError  # noqa: E402
from crema.errors import IncompleteInput, ParseError  # noqa: E402
from crema.lexer import tokenize  # noqa: E402


def run(src, argv=None, stdin=""):
    """ソースを実行して (スタック, 出力) を返す。"""
    out = io.StringIO()
    vm = VM(argv=argv, out=out, inp=io.StringIO(stdin))
    vm.run_source(src, "<test>")
    return vm.stack, out.getvalue()


def stack(src, **kw):
    return run(src, **kw)[0]


def output(src, **kw):
    return run(src, **kw)[1]


class LexerTest(unittest.TestCase):
    def test_tokens(self):
        toks = tokenize('1 -2 3.5 0x1F "a\\nb" foo [x] {y} # comment\n( a -- b ) bar')
        self.assertEqual(
            [(t.kind, t.value) for t in toks],
            [("num", 1), ("num", -2), ("num", 3.5), ("num", 31), ("str", "a\nb"),
             ("word", "foo"), ("[", "["), ("word", "x"), ("]", "]"),
             ("{", "{"), ("word", "y"), ("}", "}"), ("word", "bar")])

    def test_line_numbers(self):
        toks = tokenize('a\n"multi\nline"\nb')
        self.assertEqual([t.line for t in toks], [1, 2, 4])

    def test_unicode_escape(self):
        self.assertEqual(tokenize(r'"\u3042"')[0].value, "あ")

    def test_minus_is_a_word(self):
        self.assertEqual(tokenize("- -x 1-")[0].kind, "word")
        self.assertEqual([t.kind for t in tokenize("- -x 1-")], ["word"] * 3)

    def test_incomplete(self):
        for src in ['"abc', "( comment", "[ 1 2", ": f 1", "{ 1"]:
            with self.subTest(src=src):
                with self.assertRaises(IncompleteInput):
                    VM().compile(src)

    def test_parse_errors(self):
        for src in ["]", "}", ";", "[ : f ; ]", ": 1 ;", "-> 3", '"\\q"']:
            with self.subTest(src=src):
                with self.assertRaises(ParseError):
                    VM().compile(src)


class ArithmeticTest(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(stack("1 2 + 3 * 4 -"), [5])
        self.assertEqual(stack("7 2 /  6 2 /  7 2 div  -7 2 mod"), [3.5, 3, 3, 1])
        self.assertEqual(stack("2 10 pow  16 sqrt  2 sqrt 2 pow round"), [1024, 4, 2])
        self.assertEqual(stack("3 neg abs  2.7 floor  2.1 ceil  1 2 min  1 2 max"),
                         [3, 2, 3, 1, 2])

    def test_big_integers(self):
        self.assertEqual(stack("2 100 pow"), [2 ** 100])

    def test_division_by_zero(self):
        with self.assertRaisesRegex(CremaError, "division by zero"):
            run("1 0 /")

    def test_type_error(self):
        with self.assertRaisesRegex(CremaError, r"\+: cannot add int and string"):
            run('1 "a" +')
        with self.assertRaisesRegex(CremaError, "expected number, got bool"):
            run("true 1 -")

    def test_comparison_and_logic(self):
        self.assertEqual(stack("1 2 <  2 2 <=  3 2 >  1 1 =  1 2 !=  1 true ="),
                         [True, True, True, True, True, False])
        self.assertEqual(stack('"abc" "abd" <  { 1 2 } { 1 2 } ='), [True, True])
        self.assertEqual(stack("true false and  true false or  0 not  nil not  \"\" not"),
                         [False, True, True, True, False])


class StackTest(unittest.TestCase):
    def test_words(self):
        self.assertEqual(stack("1 dup"), [1, 1])
        self.assertEqual(stack("1 2 drop"), [1])
        self.assertEqual(stack("1 2 swap"), [2, 1])
        self.assertEqual(stack("1 2 over"), [1, 2, 1])
        self.assertEqual(stack("1 2 3 rot"), [2, 3, 1])
        self.assertEqual(stack("1 2 3 -rot"), [3, 1, 2])
        self.assertEqual(stack("1 2 nip"), [2])
        self.assertEqual(stack("1 2 tuck"), [2, 1, 2])
        self.assertEqual(stack("1 2 2dup"), [1, 2, 1, 2])
        self.assertEqual(stack("1 2 3 2 pick"), [1, 2, 3, 1])
        self.assertEqual(stack("1 2 3 depth"), [1, 2, 3, 3])
        self.assertEqual(stack("1 2 3 clear"), [])

    def test_underflow(self):
        with self.assertRaisesRegex(CremaError, "dup: stack underflow"):
            run("dup")


class FunctionTest(unittest.TestCase):
    def test_definition(self):
        self.assertEqual(stack(": square dup * ; 7 square"), [49])

    def test_hoisting_and_mutual_recursion(self):
        src = """
        10 even? 7 even?
        : even? dup 0 = [ drop true ] [ 1 - odd? ] if ;
        : odd?  dup 0 = [ drop false ] [ 1 - even? ] if ;
        """
        self.assertEqual(stack(src), [True, False])

    def test_recursion(self):
        src = ": fact dup 1 <= [ drop 1 ] [ dup 1 - fact * ] if ; 20 fact"
        self.assertEqual(stack(src), [2432902008176640000])

    def test_deep_non_tail_recursion(self):
        src = ": sum-to dup 0 = [ ] [ dup 1 - sum-to + ] if ; 100000 sum-to"
        self.assertEqual(stack(src), [5000050000])

    def test_tail_call_does_not_grow_control_stack(self):
        vm = VM(out=io.StringIO(), max_depth=50)
        vm.run_source(": loop-down dup 0 > [ 1 - loop-down ] when ; 100000 loop-down")
        self.assertEqual(vm.stack, [0])

    def test_stack_overflow_is_reported(self):
        vm = VM(out=io.StringIO(), max_depth=1000)
        with self.assertRaisesRegex(CremaError, "call stack overflow"):
            vm.run_source(": f 1 + f 1 ; 0 f")

    def test_locals(self):
        self.assertEqual(stack(": hyp -> { a b } a a * b b * + sqrt ; 3 4 hyp"), [5])
        self.assertEqual(stack("5 -> x  x x *"), [25])

    def test_locals_are_per_call(self):
        src = """
        : f -> n  n 0 > [ n 1 - f ] when  n ;
        3 f
        """
        self.assertEqual(stack(src), [0, 1, 2, 3])

    def test_function_cannot_see_callers_locals(self):
        with self.assertRaisesRegex(CremaError, "unknown word 'secret'"):
            run(": peek secret ; : f 42 -> secret peek ; f")

    def test_globals_visible_in_functions(self):
        self.assertEqual(stack("10 -> base  : add-base base + ; 5 add-base"), [15])

    def test_closures(self):
        src = """
        : adder ( n -- q ) -> n [ n + ] ;
        5 adder -> add5
        10 add5 call
        { 1 2 } 100 adder map
        """
        self.assertEqual(stack(src), [15, [101, 102]])

    def test_quote_shorthand(self):
        self.assertEqual(stack(": sq dup * ; { 1 2 3 } 'sq map"), [[1, 4, 9]])

    def test_return(self):
        src = ": sign dup 0 < [ drop -1 return ] when 0 > [ 1 ] [ 0 ] if ; -5 sign 5 sign 0 sign"
        self.assertEqual(stack(src), [-1, 1, 0])

    def test_return_from_nested_loop(self):
        src = """
        : find-first ( list pred -- x|nil )
          -> { lst pred }
          lst [ dup pred call [ return ] [ drop ] if ] each nil ;
        { 1 3 8 5 } [ 2 mod 0 = ] find-first
        { 1 3 } [ 2 mod 0 = ] find-first
        """
        self.assertEqual(stack(src), [8, None])


class ControlTest(unittest.TestCase):
    def test_if(self):
        self.assertEqual(stack('1 [ "y" ] [ "n" ] if  0 [ "y" ] [ "n" ] if'), ["y", "n"])
        self.assertEqual(stack("true [ 1 ] when  false [ 2 ] when  false [ 3 ] unless"),
                         [1, 3])

    def test_while(self):
        self.assertEqual(stack("0 -> i 0 [ i 5 < ] [ i + i 1 + -> i ] while"), [10])

    def test_times_and_for(self):
        self.assertEqual(stack("0 3 [ 1 + ] times"), [3])
        self.assertEqual(stack("{ 1 3 [ ] for }"), [[1, 2, 3]])
        self.assertEqual(stack("{ 3 1 [ ] for }"), [[]])

    def test_loop_and_break(self):
        self.assertEqual(stack("0 [ dup 5 = [ break ] when 1 + ] loop"), [5])
        self.assertEqual(stack("{ 1 10 [ dup 3 > [ drop break ] when ] for }"), [[1, 2, 3]])

    def test_nested_break_only_exits_inner_loop(self):
        src = "{ 1 3 [ -> i 1 3 [ -> j j 2 = [ break ] when { i j } ] for ] for }"
        self.assertEqual(stack(src), [[[1, 1], [2, 1], [3, 1]]])

    def test_break_outside_loop(self):
        with self.assertRaisesRegex(CremaError, "not inside a loop"):
            run(": f break ; [ f ] loop")

    def test_combinators(self):
        self.assertEqual(stack("{ 1 2 3 } [ 10 * ] map"), [[10, 20, 30]])
        self.assertEqual(stack("{ 1 2 3 4 } [ 2 mod 0 = ] filter"), [[2, 4]])
        self.assertEqual(stack("{ 1 2 3 4 } 0 [ + ] fold"), [10])
        self.assertEqual(stack("{ 1 2 } [ 1 + ] each"), [2, 3])
        self.assertEqual(stack('"ab" [ upper ] map'), [["A", "B"]])
        self.assertEqual(stack("1 2 [ 10 + ] dip"), [11, 2])
        self.assertEqual(stack("5 [ 1 + ] keep"), [6, 5])
        self.assertEqual(stack("[ 1 2 + ] call"), [3])
        self.assertEqual(stack('{ "ccc" "a" "bb" } [ len ] sort-by'), [["a", "bb", "ccc"]])

    def test_try(self):
        self.assertEqual(stack('[ 1 0 / ] [ "E:" swap + ] try'), ["E:/: division by zero"])
        self.assertEqual(stack('[ "boom" error ] [ ] try'), ["boom"])
        self.assertEqual(stack("[ 42 ] [ drop 0 ] try"), [42])

    def test_try_restores_stack_depth(self):
        self.assertEqual(stack('1 2 [ 3 4 5 "x" error ] [ drop "h" ] try'), [1, 2, "h"])

    def test_try_inside_function_across_calls(self):
        src = """
        : risky ( n -- ) 0 = [ "zero!" error ] when ;
        : safe ( n -- msg ) [ risky "ok" ] [ "caught " swap + ] try ;
        1 safe 0 safe
        """
        self.assertEqual(stack(src), ["ok", "caught zero!"])

    def test_nested_try_rethrow(self):
        src = '[ [ "inner" error ] [ "re:" swap + error ] try ] [ "outer:" swap + ] try'
        self.assertEqual(stack(src), ["outer:re:inner"])

    def test_assert(self):
        with self.assertRaisesRegex(CremaError, "assertion failed: nope"):
            run('1 2 = "nope" assert')


class DataTest(unittest.TestCase):
    def test_strings(self):
        self.assertEqual(stack('"Hello" ", " + "World" +'), ["Hello, World"])
        self.assertEqual(stack('"abc" len  "abc" upper  "  x " trim  "ab" 3 *'),
                         [3, "ABC", "x", "ababab"])
        self.assertEqual(stack('"a,b,c" "," split  { 1 2 } "-" join'), [["a", "b", "c"], "1-2"])
        self.assertEqual(stack('"hello" 1 3 slice  "hello" 0 at  "hello" reverse'),
                         ["el", "h", "olleh"])
        self.assertEqual(stack('"hello" "ll" contains?  "hello" "l" index-of'), [True, 2])
        self.assertEqual(stack('"a-b" "-" "+" replace  "A" ord  66 chr'), ["a+b", 65, "B"])
        self.assertEqual(stack('"{} + {} = {}" { 1 2 3 } format'), ["1 + 2 = 3"])
        self.assertEqual(stack('"42" num  "3.5" num  42 str  "7" int'), [42, 3.5, "42", 7])

    def test_num_error(self):
        with self.assertRaisesRegex(CremaError, "not a number"):
            run('"abc" num')

    def test_lists(self):
        self.assertEqual(stack("{ 1 2 3 }"), [[1, 2, 3]])
        self.assertEqual(stack("{ 1 2 + { 4 } }"), [[3, [4]]])
        self.assertEqual(stack("{ }"), [[]])
        self.assertEqual(stack("{ 1 2 } 3 append"), [[1, 2, 3]])
        self.assertEqual(stack("{ 1 2 } pop"), [[1], 2])
        self.assertEqual(stack("{ 1 2 3 } 1 at  { 1 2 3 } -1 at"), [2, 3])
        self.assertEqual(stack("{ 1 2 3 } 0 9 put"), [[9, 2, 3]])
        self.assertEqual(stack("0 4 range  { 3 1 2 } sort  { 1 2 3 } sum"),
                         [[0, 1, 2, 3], [1, 2, 3], 6])
        self.assertEqual(stack("{ 1 2 } unpack  1 2 3 3 pack"), [1, 2, [1, 2, 3]])
        self.assertEqual(stack("{ 1 2 } { 3 } +  { 1 2 } first  { 1 2 } rest"),
                         [[1, 2, 3], 1, [2]])

    def test_list_index_error(self):
        with self.assertRaisesRegex(CremaError, "out of range"):
            run("{ 1 } 5 at")

    def test_lists_are_mutable_references(self):
        self.assertEqual(stack("{ } -> a  a 1 append drop  a"), [[1]])
        self.assertEqual(stack("{ 1 } -> a  a copy 2 append drop  a"), [[1]])

    def test_dicts(self):
        src = 'dict "a" 1 put "b" 2 put -> d  d "a" at  d "z" 0 get  d "b" has?  d keys'
        self.assertEqual(stack(src), [1, 0, True, ["a", "b"]])
        self.assertEqual(stack('{ { "x" 1 } } to-dict "x" remove len'), [0])
        with self.assertRaisesRegex(CremaError, "key not found"):
            run('dict "nope" at')

    def test_types(self):
        self.assertEqual(stack('1 type 1.5 type "s" type true type nil type { } type dict type [ ] type'),
                         ["int", "float", "string", "bool", "nil", "list", "dict", "quote"])

    def test_display(self):
        self.assertEqual(output('{ 1 "a" 2.5 true nil { } } print'),
                         '{ 1 "a" 2.5 true nil { } }\n')
        self.assertEqual(output('[ 1 "x" [ dup ] -> y ] print'), '[ 1 "x" [ dup ] -> y ]\n')
        self.assertEqual(output('"raw" print "a" repr print'), 'raw\n"a"\n')


class IOTest(unittest.TestCase):
    def test_print_and_write(self):
        self.assertEqual(output('"a" write "b" print 1 . 1 2 .s'), "ab\n1\n<2> 1 2\n")

    def test_read_line(self):
        self.assertEqual(stack("read-line read-line read-line", stdin="x\ny\n"), ["x", "y", None])
        self.assertEqual(stack("read-all", stdin="x\ny\n"), ["x\ny\n"])

    def test_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.txt")
            src = f"""
            "{p}" -> p
            p file-exists?
            "one\\n" p write-file
            "two\\n" p append-file
            p file-exists?
            p read-file
            p read-lines
            p delete-file
            p file-exists?
            """
            self.assertEqual(stack(src), [False, True, "one\ntwo\n", ["one", "two"], False])

    def test_list_dir(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "b"), "w").close()
            open(os.path.join(d, "a"), "w").close()
            self.assertEqual(stack(f'"{d}" list-dir'), [["a", "b"]])

    def test_missing_file(self):
        with self.assertRaisesRegex(CremaError, "read-file: file not found"):
            run('"/nonexistent/file" read-file')

    def test_args(self):
        self.assertEqual(stack("args", argv=["a", "b"]), [["a", "b"]])


class MetaTest(unittest.TestCase):
    def test_eval(self):
        self.assertEqual(stack('"1 2 +" eval'), [3])
        self.assertEqual(stack('": tw 2 * ;" eval 21 tw'), [42])
        self.assertEqual(stack('5 -> x  "x 1 +" eval'), [6])

    def test_load_and_require(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "lib.crema"), "w") as f:
                f.write(': double 2 * ;\n"loaded" print\n')
            with open(os.path.join(d, "main.crema"), "w") as f:
                f.write('"lib.crema" require "lib.crema" require 21 double print\n')
            out = io.StringIO()
            vm = VM(out=out)
            vm.run_file(os.path.join(d, "main.crema"))
            self.assertEqual(out.getvalue(), "loaded\n42\n")

    def test_error_trace(self):
        # 末尾呼び出しはフレームが消えるので、末尾でない呼び出しで確認する
        src = ": inner 1 \"x\" + ;\n: outer inner 0 ;\nouter 0"
        with self.assertRaises(CremaError) as cm:
            run(src)
        e = cm.exception
        self.assertEqual(e.pos, ("<test>", 1))
        self.assertEqual([name for name, _ in e.trace], ["inner", "outer", "<main>"])

    def test_vm_reusable_after_error(self):
        vm = VM(out=io.StringIO())
        with self.assertRaises(CremaError):
            vm.run_source("1 2 nosuchword")
        vm.run_source("+")
        self.assertEqual(vm.stack, [3])


class CLITest(unittest.TestCase):
    CREMA = [sys.executable, os.path.join(ROOT, "bin", "crema")]

    def cli(self, *args, stdin=""):
        return subprocess.run(self.CREMA + list(args), input=stdin, capture_output=True,
                              text=True, timeout=60)

    def test_run_file_with_args(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "prog.crema")
            with open(p, "w") as f:
                f.write('args " " join print\n')
            r = self.cli(p, "x", "y")
            self.assertEqual((r.returncode, r.stdout), (0, "x y\n"))

    def test_eval_option(self):
        r = self.cli("-e", "6 7 * print")
        self.assertEqual((r.returncode, r.stdout), (0, "42\n"))

    def test_stdin_program(self):
        r = self.cli("-", stdin='"piped" print')
        self.assertEqual(r.stdout, "piped\n")

    def test_exit_code(self):
        self.assertEqual(self.cli("-e", "3 exit").returncode, 3)

    def test_error_exit(self):
        r = self.cli("-e", "1 nosuch")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown word 'nosuch'", r.stderr)

    def test_check(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.crema")
            with open(p, "w") as f:
                f.write("[ 1 2")
            r = self.cli("-c", p)
            self.assertEqual(r.returncode, 1)
            self.assertIn("missing ']'", r.stderr)

    def test_version_and_help(self):
        self.assertIn("crema", self.cli("--version").stdout)
        self.assertIn("usage", self.cli("--help").stdout)

    def test_missing_file(self):
        r = self.cli("/no/such/file.crema")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot open", r.stderr)


class ExamplesTest(unittest.TestCase):
    """examples/ の各プログラムが期待どおりに動くことを確認する。"""

    def example(self, name, *args, stdin=""):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "bin", "crema"),
                            os.path.join(ROOT, "examples", name), *args],
                           input=stdin, capture_output=True, text=True, timeout=120,
                           cwd=tempfile.gettempdir())
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_hello(self):
        self.assertEqual(self.example("hello.crema"), "Hello, World!\n9\n")

    def test_factorial(self):
        out = self.example("factorial.crema")
        self.assertIn("10! = 3628800", out)
        self.assertIn("30! = 265252859812191058636308480000000", out)

    def test_fib(self):
        out = self.example("fib.crema")
        self.assertIn("fib(20)       = 6765", out)
        self.assertIn("fast-fib(100) = 354224848179261915075", out)
        self.assertIn("memo-fib(90)  = 2880067194370816120", out)

    def test_fizzbuzz(self):
        lines = self.example("fizzbuzz.crema").split()
        self.assertEqual(lines[:5], ["1", "2", "Fizz", "4", "Buzz"])
        self.assertEqual(lines[14], "FizzBuzz")

    def test_quicksort(self):
        self.assertIn("sorted: { 1 3 3 9 10 27 38 43 55 82 }", self.example("quicksort.crema"))

    def test_primes(self):
        self.assertIn("count: 25", self.example("primes.crema"))

    def test_hanoi(self):
        self.assertEqual(len(self.example("hanoi.crema").splitlines()), 7)

    def test_files(self):
        out = self.example("files.crema")
        self.assertIn("total lines: 5", out)
        self.assertIn("deleted: crema-demo.txt", out)

    def test_errors(self):
        out = self.example("errors.crema")
        self.assertIn("error: division by zero is not allowed", out)
        self.assertIn("all assertions passed", out)

    def test_calc(self):
        out = self.example("calc.crema", stdin="3 4 + 2 *\n1 +\n2 0.5 ^\n")
        self.assertEqual(out, "= 14\nerror: stack underflow\n= 1.4142135623730951\n")

    def test_brainfuck(self):
        self.assertEqual(self.example("brainfuck.crema"), "Hello World!\n")

    def test_wordcount(self):
        out = self.example("wordcount.crema", stdin="the cat the dog The end")
        self.assertEqual(out.splitlines()[0], "    3  the")


if __name__ == "__main__":
    unittest.main()
