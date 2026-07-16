cmake_minimum_required(VERSION 3.25)

# ----------------------------------------------------------------------
# 1. vcpkg toolchain 自动发现
#    推荐做法：在 CMakePresets.json 里传入 CMAKE_TOOLCHAIN_FILE。
#    如果直接双击 CMake GUI 或命令行没传，则尝试读 VCPKG_ROOT 环境变量。
# ----------------------------------------------------------------------
if(NOT DEFINED CMAKE_TOOLCHAIN_FILE)
    if(DEFINED ENV{VCPKG_ROOT})
        set(CMAKE_TOOLCHAIN_FILE "$ENV{VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
            CACHE STRING "vcpkg toolchain" FORCE)
    else()
        message(FATAL_ERROR
            "VCPKG_ROOT 环境变量未设置，CMake 无法找到 vcpkg toolchain。\n"
            "请先：1) git clone https://github.com/microsoft/vcpkg.git D:\\vcpkg\n"
            "      2) 运行 D:\\vcpkg\\bootstrap-vcpkg.bat\n"
            "      3) 设置系统环境变量 VCPKG_ROOT=D:\\vcpkg\n"
            "      4) 重启 VS Code / 终端\n"
            "或者通过 CMakePresets.json 传入 CMAKE_TOOLCHAIN_FILE。")
    endif()
endif()

# 谱渡 Pudu —— 五线谱 ⇄ 简谱互转工具（OMR）
project(Pudu VERSION 0.1.0 LANGUAGES CXX)

# 启用 CTest：必须在顶层 CMakeLists 调用，才会在构建目录生成
# CTestTestfile.cmake，使 `ctest` 能发现并运行注册过的测试目标。
enable_testing()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 与 vcpkg 默认 x64-windows 动态 triplet 保持 CRT 一致 (/MD)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")

# ----------------------------------------------------------------------
# 2. 查找依赖
#    - OpenCV：图像处理
#    - pugixml：读写 MusicXML（MusicXML 本质就是 XML，用轻量 XML 库即可，
#      无需重量级的 libmusicxml2；后者未收录进 vcpkg，MSVC 源码编译也较麻烦）
# ----------------------------------------------------------------------
# find_package(OpenCV REQUIRED)  # MVP阶段暂不编译OpenCV，待网络稳定后用 opencv.org 预编译包接入
find_package(pugixml CONFIG REQUIRED)

# ----------------------------------------------------------------------
# 3. 构建目标
# ----------------------------------------------------------------------
add_executable(Pudu
    src/main.cpp
    src/musicxml_parser.cpp
    src/jianpu_converter.cpp
    src/transpose.cpp
    src/jianpu_to_staff.cpp       # 阶段 3 G1：JianpuDoc -> Score
    src/musicxml_serializer.cpp   # 阶段 3 G2：Score -> MusicXML
    src/jianpu_text_parser.cpp    # G4：简谱文本输入解析（L1 文本 -> JianpuDoc）
)

# 头文件目录（score_model.hpp / musicxml_parser.hpp 位于 include/）
target_include_directories(Pudu PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# 强制 MSVC 以 UTF-8 读取源码（源码含中文注释，默认按代码页936/GBK解析会触发
# C4819 并导致标识符被误判为"未声明"，进而连锁报错。加此选项后彻底消除）
if(MSVC)
    target_compile_options(Pudu PRIVATE /utf-8)
endif()

# target_include_directories(Pudu PRIVATE
#     ${OpenCV_INCLUDE_DIRS}
# )

target_link_libraries(Pudu PRIVATE
    # ${OpenCV_LIBS}
    pugixml::pugixml
)

# ----------------------------------------------------------------------
# 5. 单元测试（阶段 2 简谱转换）
#    极简 header-only 测试框架（test/pudu_test.hpp），不引入新依赖，
#    与项目"最小依赖"哲学一致；如需 GoogleTest 可在此替换并链接。
#    运行：build/PuduTests.exe
# ----------------------------------------------------------------------
add_executable(PuduTests
    test/pudu_test_main.cpp
    test/test_tonic.cpp
    test/test_pitch_mapping.cpp
    test/test_duration.cpp
    test/test_staff_to_jianpu.cpp
    test/test_transpose.cpp
    test/test_jianpu_to_staff.cpp   # 阶段 3 G1+G2 单测
    test/test_serializer.cpp        # 阶段 3 G2 序列化自洽（需 pugixml）
    test/test_jianpu_text_parser.cpp  # G4：简谱文本解析单测（含端到端闭环）
    src/jianpu_converter.cpp
    src/transpose.cpp
    src/jianpu_to_staff.cpp
    src/musicxml_serializer.cpp
    src/jianpu_text_parser.cpp    # G4：与 Pudu 目标并列编入（避免链接遗漏）
    src/musicxml_parser.cpp       # 提供 MusicXMLParser::parseString：test_serializer.cpp 的往返自洽测试需把序列化结果解析回 Score
)

target_include_directories(PuduTests PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/test
)

if(MSVC)
    target_compile_options(PuduTests PRIVATE /utf-8)
endif()

# 关键：PuduTests 自身编译了 src/musicxml_serializer.cpp（直接 #include <pugixml.hpp>）
# 以及 test/test_serializer.cpp（经 musicxml_parser.hpp 间接引入 pugixml.hpp），
# 因此必须链接 pugixml 才能把其 include 目录（INTERFACE_INCLUDE_DIRECTORIES）
# 传递进来，否则 MSVC 报 C1083: 无法打开包括文件 "pugixml.hpp"。
target_link_libraries(PuduTests PRIVATE pugixml::pugixml)

# 注册到 CTest：直接跑 PuduTests 可执行文件（其 main 自带 header-only
# 测试框架，返回非 0 表示有失败）。这样 `ctest` 即可驱动全套单元测试。
add_test(NAME PuduTests COMMAND PuduTests)

# ----------------------------------------------------------------------
# 4. Windows 下运行时 DLL 提示
#    OpenCV 的 DLL 位于 vcpkg_installed/x64-windows/bin，运行时需要能找到。
#    最省事的做法：在 VS Code 中按 F5 调试时，把该目录加进 PATH（见 README）。
# ----------------------------------------------------------------------
