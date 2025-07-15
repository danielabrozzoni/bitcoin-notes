<!-- desc: Why macros use do { ... } while(false); to behave like safe single statements. -->

# Macro Safety: The do-while-false Idiom

It's common to wrap multi-statement macros in a `do { ... } while(false)` block. This is done to make the macro safe when used inside control structures like `if` without braces; without it, macros that expand to multiple statements can behave in unexpected ways.

For example, say I define a macro like this:

```cpp
#define my_macro do_something(); do_something_else();
```

And then I use it like this:

```cpp
if (condition)
  my_macro;
```

That expands to:

```cpp
if (condition)
  do_something();
do_something_else();  // ← this part is **not** inside the if block!
```

This leads to a bug, since `do_something_else()` always runs, regardless of the condition.

By wrapping the macro like this:

```cpp
#define my_macro do { do_something(); do_something_else(); } while (false)
```

Now when it's used:

```cpp
if (something)
  my_macro;
```

It expands to:

```cpp
if (something)
  do { do_something(); do_something_else(); } while (false);
```

This behaves as expected: everything stays inside the if.

The `do { ... } while(false)` pattern makes macros act like a single statement!
