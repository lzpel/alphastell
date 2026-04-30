# syntax=docker/dockerfile:1.7

# ============================================================
# Stage 1: openapi-ts でフロントエンド用 TypeScript クライアントを生成
# ============================================================
FROM node:20-alpine AS openapi-client
WORKDIR /work/frontend/openapi
COPY frontend/openapi/package.json frontend/openapi/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/openapi/openapi.json frontend/openapi/out.ts ./
RUN npx openapi-ts --file ./out.ts

# ============================================================
# Stage 2: Next.js 静的エクスポートを生成
# ============================================================
FROM node:20-alpine AS next-build
WORKDIR /work/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=openapi-client /work/frontend/client /work/frontend/client
COPY frontend/app ./app
COPY frontend/public ./public
COPY frontend/next.config.ts frontend/tsconfig.json frontend/next-env.d.ts ./
RUN npm run build

# ============================================================
# Stage 3: Rust バイナリをビルド (frontend-embed feature ON)
#   provided:al2023 default GCC 11 と cadrum prebuilt OCCT (GCC 14+ ABI) の
#   `__cxa_call_terminate` 衝突回避のため gcc14 を入れて切替 (lzpel/cadrum#147)。
# ============================================================
FROM public.ecr.aws/lambda/provided:al2023 AS rust-build
RUN dnf install -y gcc14 gcc14-c++ cmake make tar gzip pkgconfig openssl-devel \
    && dnf clean all \
    && ln -sf /usr/bin/gcc14-gcc /usr/local/bin/gcc \
    && ln -sf /usr/bin/gcc14-gcc /usr/local/bin/cc \
    && ln -sf /usr/bin/gcc14-g++ /usr/local/bin/g++ \
    && ln -sf /usr/bin/gcc14-g++ /usr/local/bin/c++ \
    && ln -sf /usr/bin/gcc14-cpp /usr/local/bin/cpp
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:/usr/local/bin:${PATH}" \
    CC=/usr/local/bin/gcc \
    CXX=/usr/local/bin/g++ \
    CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=/usr/local/bin/gcc
WORKDIR /var/task
COPY Cargo.toml Cargo.lock ./
COPY src ./src
COPY --from=next-build /work/frontend/out /var/task/frontend/out
RUN cargo build --release --features frontend-embed
RUN find target/release -maxdepth 1 -type f -executable | xargs -IX install -D X -t target/bin/

# ============================================================
# Stage 4: Runtime (AWS Lambda Web Adapter + alphastell バイナリ)
# ============================================================
FROM public.ecr.aws/lambda/provided:al2023 AS runner
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.3 /lambda-adapter /opt/extensions/lambda-adapter
ENV PORT=8080
COPY --from=rust-build /var/task/target/bin/. ./
ENTRYPOINT ["./alphastell", "server"]
