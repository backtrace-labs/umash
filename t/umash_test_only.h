#ifndef UMASH_TEST_ONLY_H
#define UMASH_TEST_ONLY_H
/**
 * The prototypes in this header file are only exposed for testing,
 * when UMASH is built with -DUMASH_TEST_ONLY.
 */

#ifndef UMASH_TEST_ONLY
#error "umash_test_only.h should only be used with -DUMASH_TEST_ONLY"
#endif

#endif /* !UMASH_TEST_ONLY_H */
