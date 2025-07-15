<!-- desc: Comparing std::mutex and std::recursive_mutex, with a hands-on nested logging example. -->

# Mutex vs Recursive Mutex

`std::mutex` is used to protect shared resources from concurrent acces by multiple threads. It can only be locked once per thread, and if you lock more than once, it will deadlock.

`std::recursive_mutex` is a specialized type of mutex that allows the same thread to lock the mutex multiple times recursively.

- A thread that has already acquired the lock can call lock() multiple times on the same std::recursive_mutex without deadlocking. Each successful lock() call increments an internal lock count.
- For the mutex to be released and become available for other threads, the thread that acquired it must call unlock() the same number of times it called lock(). The mutex is only truly released when the internal lock count reaches zero.
- It is particularly useful in scenarios where a function that acquires a lock might, in turn, call another function that also attempts to acquire the same lock. Without a recursive_mutex, this would lead to a deadlock.
- Recursive mutex is generally slower than mutex, because it requires additional internal state to track the lock count and the ID of the thread that owns the mutex (so that when a new lock is called, system can understand if requesting thread is the current owner or some other thread)

## 🔐 Exercise: "Nested Logging"

Warning: this exercise is AI generated, but still useful IMHO

```cpp
// Scenario:
// You’re building a very basic logging system where multiple threads can log messages.
// The logging function can optionally log nested details, like timestamps or metadata —
// and these nested calls reuse the logging function itself.
//
// Your Task:
// 1. Implement a class `Logger` that contains:
//    - A function `Log(const std::string& msg)` that writes a message to `std::cout`.
//    - A `std::mutex` or `std::recursive_mutex` to protect the logging.
//
// 2. Inside `Log()`, simulate a nested call:
//    - After printing the main message, call a helper function `LogDetails()`.
//    - `LogDetails()` should also call `Log()` to write "timestamp: [now]".
//
// 3. Spawn multiple threads that call `Log("message from thread X")`.
//
// 4. Try this with:
//    - `std::mutex` — see what happens 😈
//    - Then switch to `std::recursive_mutex` — and see the difference ✅
//
// 🔄 Things to explore:
// - What happens when you try to lock a `std::mutex` twice in the same thread?
// - How does `std::recursive_mutex` handle it differently?
// - Try putting a `std::this_thread::sleep_for()` between logs to simulate delay.
// - Can you make it crash? Can you fix it?
```
