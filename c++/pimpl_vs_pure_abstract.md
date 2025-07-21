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

If you want to know more: [Bitcoin Core Review Club #22950](https://bitcoincore.reviews/22950)

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
We define the make() method here, since DogImpl is now visible.

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

Example from Bitcoin Core: `AddrMan` and `AddrManImpl`.

Interface object owns a pointer to the implementation object. Whenever there is a method call, the call gets forwarded to the implementation object to fulfill, and any return values are routed back through the same path.

## Step 1: Declare base class

The public-facing class holds a pointer to its hidden implementation. At this stage, we only declare the interface, no method definitions yet.

- Declare a forward-declared inner class Impl, which will hold the actual data and logic.
- Store a std::unique_ptr<Impl> as a private (or protected) member.
- Declare the constructor and destructor, but don’t define them here, the Impl type is still incomplete.
- Declare all public methods.

```cpp
// in dog.h
#include <string>
#include <memory>

class Dog {
    protected:
        class Impl;
        std::unique_ptr<Impl> m_impl;

    public:
        // Constructor and destructor are only declared here - we can't define them yet
        // because Impl is an incomplete type
        Dog(std::string name);
        ~Dog();

        void say_name();
};
```

## Step 2: Implementation class

Define the Impl class, which holds the actual private data and method implementations.

Then define the base class's methods: each forwards the call to the implementation.

```cpp
// in dog.cpp
#include "dog.h"
#include <iostream>

class Dog::Impl {
    // Holds the actual private data
    std::string name;

    public:
        Impl(std::string name) : name(name) {}
        ~Impl() {}

        void say_name() {
            std::cout << this->name << std::endl;
        }
};

Dog::Dog(std::string name): m_impl(std::make_unique<Impl>(name)) {}

Dog::~Dog() = default;

void Dog::say_name() {
    m_impl->say_name();
}
```

## Step 3: Usage

Client code uses only the Dog interface, it has no access to or knowledge of the implementation.

```cpp
int main() {
    Dog dog = Dog("willy");
    dog.say_name();
}
```

## Choosing Between Pure Abstract Class and PIMPL

|                          | Pure Abstract Class                                  | PIMPL                                               |
|--------------------------|------------------------------------------------------|-----------------------------------------------------|
| **Core idea**            | Define a pure interface; implementation is in a derived class | Encapsulate implementation via a pointer to a hidden `Impl` class |
| **Runtime cost**         | Virtual function dispatch (vtable lookup)            | Pointer indirection (usually slightly cheaper)      |
| **Memory layout**        | Separate allocations for interface + impl            | Single interface object holds the pointer           |
| **Extensibility**        | Supports multiple implementations                     | Not meant to be subclassed                          |
| **Binary stability**     | Interface changes can break client code              | Internal changes don’t affect interface             |
