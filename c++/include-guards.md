<!-- desc: How include guards prevent multiple inclusion in C++ headers, and how to write them. -->

# Include guards

Include guards are used to avoid the problem of double/circular inclusion: every time you `#include`, the pre-processor copy-pastes the whole content of the included file into the includer, which can lead to errors.

Include guards help avoid this by ensuring a file is included only once.


For example, in file myfile.h, you would put:
```
// !! NO CODE HERE
#ifndef PROJECT_NAME_MYFILE_H
#define PROJECT_NAME_MYFILE_H

// Your code goes here...

#endif
// !! NO CODE HERE
```

- `#ifndef` checks if the identifier (PROJECT_NAME_SCANNER_H) is not yet defined
- `#define` defines the identifier, marking the file as included
- `#endif` ends the guard

You can use whatever name you want for the `PROJECT_NAME_MYFILE_H` identifier, but it's common practice to use the project name and the filename to avoid potential naming conflicts 
