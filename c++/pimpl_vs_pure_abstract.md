<!-- desc: Explains the PIMPL and Pure Abstract Class patterns for hiding implementation details. -->

# PIMPL and Pure Abstract Class

In C++, any time we change the internal implementation of a class, all code that depends on that class needs to be recompiled. This happens because:
- Changing private members (adding/removing/changing them) can affect the size and layout of the object.
- Overload resolution: In C++, all member functions (even private ones) are considered during overload resolution. That means simply changing or adding a private method can influence which function gets picked during compilation. 

To avoid unnecessary recompilation, a common approach is to separate the implementation details of a class from its public interface. Two popular patterns for doing this are the Pure Abstract Class pattern and the PIMPL (Pointer to IMPLementation) pattern.

In both cases, the original class is split into two parts:
- An abstract interface, which is exposed to the outside world.
- A concrete implementation, which hides all the internal details.

With this setup, when internal implementation changes, only the implementation file needs to be recompiled. Clients that include just the abstract interface are unaffected and don’t need to be rebuilt.

TODO: insert markdown index?

## Pure Abstract Class pattern

Example from Bitcoin Core: `PeerManager` and `PeerManagerImpl`

This pattern is used to separate interface from implementation using classic C++ polymorphism. The idea is that you expose only a pure virtual base class to the outside world, and hide the concrete implementation behind it.

### Step 1: Define the abstract base class

- Has a static method make() that returns a unique_ptr to itself (used as a constructor).
- The destructor is `virtual`, as required for polymorphic classes. Without it, deleting a derived object through a base pointer would cause undefined behavior, since C++ would only call the base destructor).
- All methods are declared `virtual`.


```cpp
// in file dog.h
#include <memory>

class Dog {
    public:
        static std::unique_ptr<Dog> make (std::string name);

        virtual ~Dog() = default;

        virtual void say_name() = 0;
};
```

### Step 2: Define the implementation class

- Include the header for the abstract base class
- Define the concrete implementation class (`DogImpl`), which inherits from base class (`Dog`)
- Mark the implementation class as final to make it clear it's just an internal detail that shouldn't be subclassed. This can also help the compiler optimize virtual calls a bit better.
- Implement the constructor and all virtual methods (each marked with `override`)
- Declare any private members here

```cpp
// in file dog.cpp
#include "dog.h"
#include <memory>
#include <iostream>

class DogImpl final: public Dog {
    public:
        DogImpl(std::string name):
            name(name) {}

        void say_name() override {
            std::cout << this->name << std::endl;
        }

    private:
        std::string name;
};
```

### Step 3: Implement the factory method
We couldn't define the `make()` method earlier, since `DogImpl` wasn't visible yet.

```cpp
// in file dog.cpp
std::unique_ptr<Dog> Dog::make(std::string name) {
    return std::make_unique<DogImpl>(name);
}
```

### Usage
The client code interacts only with the `Dog` interface. It doesn't need to know or care about `DogImpl`.

```cpp
int main() {
    std::string name = "willy";
    std::unique_ptr<Dog> my_dog = Dog::make(name);
    my_dog->say_name();
}
```

## PIMPL
TODO


## Drawbacks, which one to choose
TODO
