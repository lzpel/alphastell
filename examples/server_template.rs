use mandolin;

fn main() {
    // 1. Read OpenAPI file (use openapi_loader to handle JSON / YAML transparently)
    let f = std::fs::File::open("./frontend/openapi.json").unwrap();
    let api = mandolin::openapi_loader::openapi_load(f).unwrap();

    // 2. Create environment
    let env = mandolin::environment(api).unwrap();

    // 3. Render
    let output = env.get_template("RUST_AXUM").unwrap().render(0).unwrap();
    
    std::fs::write("src/out.rs", output).unwrap();
}