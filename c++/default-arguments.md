# Default arguments in C++ functions

In C++, default arguments allow function parameters to have default values, making them optional when calling the function.

They must be specified in the function declaration, so tipically in the header file.

```cpp
	  // In header (.h)
	  void MyFunction(bool flag = true);
	  
	  // In source (.cpp)
	  void MyFunction(bool flag) {
	      // ...
	  }
```

When calling `MyFunction`, you can either specify the argument explicitly or rely on the default value:

```cpp
// Both are ok:
MyFunction(true);  // Flag is explicitly set to true

MyFunction();      // Flag uses the default value (true)
```
