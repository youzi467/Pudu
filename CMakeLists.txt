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
    src/omr_adapter.cpp           # 阶段1 OMR 黑盒集成适配层
    src/jianpu_postcorrect.cpp    # P1-1：后处理音乐规则引擎（确定性自修/标记）
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

# 注入 tools/ 绝对路径（转正斜杠，避免 Windows 反斜杠在字符串字面量中成非法转义），
# 供 omr_adapter 的子进程引擎（oemer/audiveris 预设）定位运行器脚本
file(TO_CMAKE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/tools" PUDU_TOOLS_DIR_FWD)
target_compile_definitions(Pudu PRIVATE "PUDU_TOOLS_DIR=\"${PUDU_TOOLS_DIR_FWD}\"")

# target_include_directories(Pudu PRIVATE
#     ${OpenCV_INCLUDE_DIRS}
# )

target_link_libraries(Pudu PRIVATE
    # ${OpenCV_LIBS}
    pugixml::pugixml
)

# ----------------------------------------------------------------------
# 5. 单元测试目标已移除（2026-08-13 仓库清理）
#    test/（C++ 单测，header-only 自研框架）随清理归档至 to_be_delete/，
#    PuduTests 目标随之下线，仅保留 Pudu 主程序目标。若需恢复测试，
#    从 to_be_delete/test/ 搬回并恢复本目标即可。
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# 4. Windows 下运行时 DLL 提示
#    OpenCV 的 DLL 位于 vcpkg_installed/x64-windows/bin，运行时需要能找到。
#    最省事的做法：在 VS Code 中按 F5 调试时，把该目录加进 PATH（见 README）。
# ----------------------------------------------------------------------
