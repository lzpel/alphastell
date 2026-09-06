# Policy

- Prioritize reducing functions, structures, traits, and dependencies over increasing them
- Prioritize requiring minimal effort over misleading the user when deciding between them
- For implementation instructions, run tests to verify after implementation
- No module-level docstring, no top-level constants and codes, no shebang
- All arguments and returns of all function must have typing annotation 
- Only inline comments(`code() # why`), remove comments that the code already say

## examples/al_(\d+).py

- all output from script al_(\d\d).py must be in out/al_$1_<name>.<extension>
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
	out.write_text(report(**fields), encoding="utf-8")

def report(**kwargs)->str:
	return """# テンプレート (make al-00)
実験結果をmarkdownで説明
$$mu0={mu0}$$
""".format(**kwargs)

if __name__ == "__main__":
	main()
```