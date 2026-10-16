#!/bin/sh
# Vercel이 화면을 올릴 때 한 번 돈다 (vercel.json의 buildCommand).
# 환경변수 API_BASE_URL(서버 주소)을 화면이 읽는 config.js로 적는다. 끝의 / 는 뗀다.
# 비밀(API 키)은 여기에 두지 않는다: 이 값은 화면에 실려 누구나 볼 수 있다.
node -e 'const url = (process.env.API_BASE_URL || "").trim().replace(/\/+$/, "");
if (url && !/^https:\/\/[^\s"<>]+$/.test(url)) { console.error("API_BASE_URL은 https:// 로 시작하는 주소여야 합니다"); process.exit(1); }
require("fs").writeFileSync("config.js", "window.API_BASE_URL = " + JSON.stringify(url) + ";\n");
console.log("config.js: API_BASE_URL =", url || "(비어 있음: 기본 주소를 씀)");'
