# Policy

- Prioritize reducing functions, structures, traits, and dependencies over increasing them
- Prioritize requiring minimal effort over misleading the user when deciding between them

# Agent

- For implementation instructions, run tests to verify after implementation
- Remove comments that the code already says and keep a comment within two lines.

## examples/al_(\d\d).py

- all output from script al_(\d\d).py must be in out/al_$1_<name>.<extension>
- all pdf report like al_$1_<name>.pdf must be uploaded into github release.
- all arguments and returns of all function must have typing annotation 
- no shebang (unless the interpreter is a container), no module-level docstring, no top-level constants and codes except TEMPLATE
- The first function must be main, and all constants, including wout(the input vmec path) and out(the output path), must be passed as arguments to it with the default value.

```examples/al_00_template.py
import math
import pathlib

def main(
	wout: pathlib.Path = pathlib.Path(__file__).resolve().parent / "wout_vmec.nc",
	out: pathlib.Path = pathlib.Path("out") / pathlib.Path(__file__).with_suffix(".md").name,
) -> None:
    fields={
        "mu0": 4e-7 * math.pi
    }
	out.write_text(TEMPLATE.format(**fields), encoding="utf-8")

TEMPLATE = """# テンプレート (make al-00)
実験結果をmarkdownで説明
$$mu0={mu0}$$
"""

if __name__ == "__main__":
	main()
```