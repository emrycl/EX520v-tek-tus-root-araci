typedef unsigned long usize;

extern int dm_shmInit(int entity, int create);
extern int rdp_getObjStruct(int role, const char *oid, void *stack, int size, void *object);
extern int rdp_setObjStruct(int role, const char *oid, void *stack, void *object, int flags);

int rsl_checkSecurity(void)
{
    return 1;
}

static long syscall3(long number, long first, long second, long third)
{
    register long x0 __asm__("x0") = first;
    register long x1 __asm__("x1") = second;
    register long x2 __asm__("x2") = third;
    register long x8 __asm__("x8") = number;
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
    return x0;
}

static void write_number(int value)
{
    char buffer[16];
    char digits[12];
    usize used = 0;
    usize count = 0;
    unsigned number = value < 0 ? (unsigned)-value : (unsigned)value;
    if (value < 0) buffer[used++] = '-';
    do {
        digits[count++] = (char)('0' + number % 10);
        number /= 10;
    } while (number);
    while (count) buffer[used++] = digits[--count];
    buffer[used++] = '\n';
    syscall3(64, 1, (long)buffer, (long)used);
}

void _start(void)
{
    unsigned short root_stack[25] = {1, 1};
    unsigned short admin_stack[25] = {1, 2};
    unsigned char root[512] = {0};
    unsigned char admin[512] = {0};
    char password[33] = {0};
    long length = syscall3(63, 0, (long)password, 32);
    while (length > 0 && (password[length - 1] == '\n' || password[length - 1] == '\r')) length--;
    if (length < 8 || dm_shmInit(0, 0) != 0 ||
        rdp_getObjStruct(1, "DEV2_USERS_USER", root_stack, sizeof(root), root) != 0 ||
        rdp_getObjStruct(1, "DEV2_USERS_USER", admin_stack, sizeof(admin), admin) != 0) {
        write_number(1);
    } else {
        for (int index = 0; index < 69; index++) root[index] = admin[index];
        root[2] = 1;
        for (int index = 0; index < 65; index++) root[134 + index] = 0;
        for (int index = 0; index < length; index++) root[134 + index] = (unsigned char)password[index];
        write_number(rdp_setObjStruct(1, "DEV2_USERS_USER", root_stack, root, 0x82));
    }
    for (int index = 0; index < 33; index++) password[index] = 0;
    for (int index = 0; index < 512; index++) root[index] = 0;
    for (int index = 0; index < 512; index++) admin[index] = 0;
    register long x0 __asm__("x0") = 0;
    register long x8 __asm__("x8") = 93;
    __asm__ volatile("svc 0" : : "r"(x0), "r"(x8) : "memory");
    __builtin_unreachable();
}
