#ifndef PUDU_TEST_HPP
#define PUDU_TEST_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · 极简单元测试框架（header-only，零外部依赖）
//
// 设计动机：
//   - 项目当前仅依赖 pugixml，遵循"最小依赖"哲学；网络还有 TLS 拦截，
//     不宜为测试再引入 vcpkg 依赖。故自研一个 ~120 行的 header-only 框架。
//   - 提供 TEST / EXPECT_TRUE / EXPECT_FALSE / EXPECT_EQ / EXPECT_NE /
//     EXPECT_NO_THROW，覆盖正常路径、边界条件、异常场景断言。
//   - 若日后要换 GoogleTest：把 test/ 下文件改用 gtest 宏、CMake 里
//     把 PuduTests 链接 gtest 即可，测试逻辑无需改写。
// ----------------------------------------------------------------------

#include <exception>
#include <functional>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace pudu_test {

struct TestCase {
    std::string name;
    std::function<void()> fn;
};

// 测试注册表（inline + 函数内 static，跨 TU 单一实例）
inline std::vector<TestCase>& registry() {
    static std::vector<TestCase> r;
    return r;
}

inline int& g_failures() { static int f = 0; return f; }
inline int& g_checks()   { static int c = 0; return c; }

struct Registrar {
    Registrar(const std::string& name, std::function<void()> fn) {
        registry().push_back({name, std::move(fn)});
    }
};

inline void reportFailure(const char* file, int line,
                          const char* expr, const std::string& detail) {
    ++g_failures();
    std::cerr << "  [FAIL] " << file << ":" << line
              << "  (" << expr << ")  " << detail << "\n";
}

// 运行全部测试，返回失败测试数（0 = 全绿）
inline int runAll() {
    const int total = static_cast<int>(registry().size());
    int failedTests = 0;
    std::cout << "[====] 运行 " << total << " 个测试\n";
    for (auto& t : registry()) {
        int before = g_failures();
        int beforeC = g_checks();
        bool threw = false;
        std::string what;
        try {
            t.fn();
        } catch (const std::exception& e) {
            threw = true; what = e.what();
        } catch (...) {
            threw = true; what = "unknown";
        }
        bool ok = !threw && (g_failures() == before);
        if (ok) {
            std::cout << "  [PASS] " << t.name
                      << " (" << (g_checks() - beforeC) << " 断言)\n";
        } else {
            ++failedTests;
            if (threw)
                std::cerr << "  [EXCEPTION] " << t.name << ": " << what << "\n";
            else
                std::cerr << "  [FAIL] " << t.name << "\n";
        }
    }
    std::cout << "[====] " << (total - failedTests) << "/" << total
              << " 通过，共 " << g_failures() << " 处断言失败\n";
    return failedTests;
}

} // namespace pudu_test

#define PUDU_CAT_(a, b) a##b
#define PUDU_CAT(a, b) PUDU_CAT_(a, b)

// 定义一个测试：注册到全局表，main 中统一运行
#define TEST(name)                                                         \
    static void name();                                                    \
    static ::pudu_test::Registrar PUDU_CAT(reg_, __LINE__)(#name, name);   \
    static void name()

#define EXPECT_TRUE(expr)                                                  \
    do {                                                                   \
        ++::pudu_test::g_checks();                                         \
        if (!(expr)) ::pudu_test::reportFailure(__FILE__, __LINE__,        \
            #expr, "期望为真");                                             \
    } while (0)

#define EXPECT_FALSE(expr)                                                 \
    do {                                                                   \
        ++::pudu_test::g_checks();                                         \
        if ((expr)) ::pudu_test::reportFailure(__FILE__, __LINE__,         \
            #expr, "期望为假");                                             \
    } while (0)

#define EXPECT_EQ(a, b)                                                    \
    do {                                                                   \
        ++::pudu_test::g_checks();                                         \
        auto _va = (a); auto _vb = (b);                                    \
        if (!(_va == _vb)) {                                               \
            std::ostringstream _os;                                        \
            _os << "期望 " << _va << " == " << _vb;                        \
            ::pudu_test::reportFailure(__FILE__, __LINE__,                 \
                #a " == " #b, _os.str());                                  \
        }                                                                  \
    } while (0)

#define EXPECT_NE(a, b)                                                    \
    do {                                                                   \
        ++::pudu_test::g_checks();                                         \
        auto _va = (a); auto _vb = (b);                                    \
        if (!(_va != _vb)) {                                               \
            std::ostringstream _os;                                        \
            _os << "期望 " << _va << " != " << _vb;                        \
            ::pudu_test::reportFailure(__FILE__, __LINE__,                 \
                #a " != " #b, _os.str());                                  \
        }                                                                  \
    } while (0)

// 表达式不应抛出（捕获标准异常与未知异常均记失败）
#define EXPECT_NO_THROW(expr)                                              \
    do {                                                                   \
        ++::pudu_test::g_checks();                                         \
        try { (void)(expr); }                                              \
        catch (const std::exception& e) {                                  \
            ::pudu_test::reportFailure(__FILE__, __LINE__, #expr,          \
                std::string("不应抛异常，但抛出: ") + e.what());            \
        }                                                                  \
        catch (...) {                                                      \
            ::pudu_test::reportFailure(__FILE__, __LINE__, #expr,          \
                "不应抛异常，但抛出了未知异常");                             \
        }                                                                  \
    } while (0)

// 表达式应抛出（标准异常或未知异常均可；用于异常路径/非法输入断言）
#define EXPECT_THROW(expr)                                                 \
    do {                                                                   \
        ++::pudu_test::g_checks();                                         \
        bool _threw = false;                                              \
        try { (void)(expr); }                                              \
        catch (...) { _threw = true; }                                     \
        if (!_threw)                                                       \
            ::pudu_test::reportFailure(__FILE__, __LINE__, #expr,          \
                "期望抛出异常，但未抛出");                                  \
    } while (0)

#endif // PUDU_TEST_HPP
