# Nubli Usage Guide

Guía rápida para usar Nubli localmente.

```txt
 _   _       _     _ _
| \ | |_   _| |__ | (_)
|  \| | | | | '_ \| | |
| |\  | |_| | |_) | | |
|_| \_|\__,_|_.__/|_|_|
```

Nubli anonimiza documentos **sin subirlos a internet**. Sirve para preparar PDFs, imágenes, DOCX, XLSX, CSV, Markdown y texto antes de compartirlos con herramientas de IA.

---

## 1. Comando instalado

Después de correr `./install.sh`, el comando queda aquí:

```bash
~/.local/bin/nubli
```

Si `nubli` no funciona directo, usa la ruta completa:

```bash
~/.local/bin/nubli --help
```

O agrega esto a tu shell profile (`~/.zshrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Luego abre una terminal nueva y prueba:

```bash
nubli --help
```

---

## Cómo descargar / instalar el CLI

### En esta Mac ya está instalado

```bash
nubli --help
nubli
```

El binario local está en:

```bash
~/.local/bin/nubli
```

### Si otra persona descarga el repo

```bash
git clone <repo-url> nubli
cd nubli
./install.sh
nubli
```

### Si lo tienes como ZIP

```bash
unzip nubli.zip
cd nubli
./install.sh
nubli
```

### Ver ayuda de instalación desde el CLI

```bash
nubli --help-install
```

---

## Demo rápida con datos sintéticos

Puedes probar Nubli con cualquier PDF o documento sintético. Ejemplo:

```bash
nubli ./examples/sample.md \
  --replace "Acme S A=Demo Company" \
  --replace "legal@acme.example=person@example.local" \
  --format markdown \
  --require-all-rules \
  --strict-pii \
  -o ./sample-anon.md \
  --report ./sample-report.json
```

Verificación esperada: el output no conserva `Acme` ni `legal@acme.example`; sí conserva los placeholders `Demo Company` y `person@example.local`.

---

## 2. Modo más fácil: menú interactivo

```bash
nubli
```

Ahora abre un wizard/menu real:

1. **Anonymize a file**
2. **Show install/download help**
3. **Show quick examples**
4. **Exit**

Si eliges anonimizar, te pregunta paso a paso:

1. archivo de entrada,
2. formato de salida: Markdown, texto o imágenes,
3. archivo/carpeta de salida,
4. reglas JSON o reglas manuales,
5. modo seguro (`--require-all-rules`, `--strict-pii`),
6. OCR/header/logos si es PDF o imagen.

Úsalo cuando no quieras acordarte de flags.

Para ver instrucciones de instalación desde el CLI:

```bash
nubli --help-install
```

---

## 3. Anonimizar texto/PDF a Markdown

```bash
nubli documento.pdf \
  --replace "Empresa Real S A=Empresa Demo" \
  --replace "Juan Pérez=Persona Demo" \
  --replace "juan@empresa.com=persona@demo.local" \
  --format markdown \
  -o documento-anon.md
```

Esto extrae texto del PDF y genera un Markdown anonimizado.

---

## 4. Anonimizar visualmente un PDF por páginas

Para documentos donde el nombre aparece como logo, encabezado o imagen:

```bash
nubli documento.pdf \
  --format images \
  --replace "Empresa Real S A=Empresa Demo" \
  --redact-header 0.12 \
  --header-text "EMPRESA DEMO" \
  -o documento-anon-pages
```

`--redact-header 0.12` tapa el 12% superior de cada página.

También puedes usar píxeles:

```bash
--redact-header 160
```

---

## 5. Tapar logos, sellos o zonas manuales

Formato:

```txt
x,y,width,height=Texto visible
```

Ejemplo:

```bash
nubli documento.pdf \
  --format images \
  --replace "Empresa Real S A=Empresa Demo" \
  --redact-region "40,30,220,90=LOGO REDACTED" \
  --redact-region "900,20,260,80=CLIENTE" \
  -o documento-anon-pages
```

Útil para:

- logos,
- encabezados raros,
- sellos,
- marcas de agua,
- texto que no se detecta como texto real.

---

## 6. Usar muchas reglas con JSON

Crea `rules.json`:

```json
{
  "Empresa Real S A": "Empresa Demo",
  "Juan Pérez": "Persona Demo",
  "juan@empresa.com": "persona@demo.local",
  "507-6000-0000": "TEL-0000",
  "8-888-888": "ID-0000"
}
```

Luego corre:

```bash
nubli documento.docx --rules rules.json -o documento-anon.md
```

---

## 7. Modo seguro recomendado

Para documentos sensibles usa:

```bash
nubli documento.pdf \
  --format images \
  --rules rules.json \
  --require-all-rules \
  --strict-pii \
  --redact-header 0.12 \
  -o documento-anon-pages
```

Qué hacen esos flags:

| Flag | Qué hace |
|---|---|
| `--require-all-rules` | Pregunta/falla si alguna regla no encontró match. |
| `--strict-pii` | Pregunta/falla si todavía parecen quedar correos, teléfonos, IDs o nombres. |
| `--redact-header` | Tapa encabezado/logo superior. |
| `--redact-region` | Tapa zonas manuales específicas. |

---

## 8. Cuando Nubli dice “zero replacements”

Si ves algo como:

```txt
zero replacements/redactions matched
```

Significa que Nubli **no encontró nada para reemplazar** y se negó a generar un archivo posiblemente inseguro.

Soluciones:

1. Revisa que la regla esté bien escrita.
2. Usa una regla más simple:

```bash
--replace "Empresa Real=Empresa Demo"
```

3. Para PDFs escaneados, usa OCR:

```bash
--ocr
```

4. Si el nombre está como imagen/logo, usa:

```bash
--redact-header 0.12
# o
--redact-region "x,y,w,h=REDACTED"
```

5. Solo si de verdad quieres permitir cero matches:

```bash
--allow-zero-replacements
```

No recomendado para documentos confidenciales.

---

## 9. OCR

Nubli instaló las librerías Python para OCR, pero el motor local Tesseract puede requerir instalación del sistema.

En macOS:

```bash
brew install tesseract tesseract-lang
```

Luego:

```bash
nubli documento-escaneado.pdf \
  --ocr \
  --format markdown \
  --replace "Empresa Real=Empresa Demo" \
  -o salida.md
```

---

## 10. Ver reporte JSON

```bash
nubli documento.pdf \
  --replace "Empresa Real=Empresa Demo" \
  --report report.json \
  -o salida.md
```

El reporte incluye:

- reglas usadas,
- cuántos matches tuvo cada regla,
- redacciones visuales,
- sugerencias de datos sensibles.

---

## 11. Salida visual y modo silencioso

Por defecto, Nubli ahora muestra:

- ASCII title,
- Nubli cat,
- archivo de entrada,
- formato,
- reglas cargadas,
- progreso,
- matches por regla,
- outputs generados.

Si quieres usarlo en scripts y solo imprimir rutas/errores:

```bash
nubli documento.pdf --replace "Empresa=Demo" -o salida.md --quiet
```

Si quieres progreso pero sin la mascota:

```bash
nubli documento.pdf --replace "Empresa=Demo" -o salida.md --no-pet
```

---

## 12. Comandos útiles

Ver ayuda:

```bash
nubli --help
```

Instalar de nuevo:

```bash
./install.sh
```

Ocultar la mascota ASCII:

```bash
NUBLI_NO_PET=1 ./install.sh
# o
./install.sh --no-pet
```

Desinstalar el shim:

```bash
./install.sh
# elige opción 4
```

---

## 12. Regla de oro

Si el documento es importante o confidencial:

1. usa `--strict-pii`,
2. usa `--require-all-rules`,
3. tapa headers/logos con `--redact-header`,
4. revisa visualmente el resultado antes de compartirlo.

Nubli ayuda, pero no reemplaza revisión humana en documentos sensibles.
