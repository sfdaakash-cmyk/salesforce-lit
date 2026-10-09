## Usage Reference

### 1. Retrieve Server Schema & Information (`info`)
Displays the registered tools, parameters, descriptions, and resources hosted by the MCP server:
```bash
./salesforce-docs info
```

### 2. List Document Collections (`collections`)
Shows indexed collections with document/chunk counts and timestamps:
```bash
./salesforce-docs collections
```

#### Filtering and Sorting:
- **Filter by root source** (`admin`, `developer`, `legacydeveloper`, `architect`, `mulesoft`, `tableau`):
  ```bash
  ./salesforce-docs collections --source developer
  ```
- **Filter by text search**:
  ```bash
  ./salesforce-docs collections --filter lwc
  ```
- **Sort by metric** (`name`, `docs`, `chunks`):
  ```bash
  ./salesforce-docs collections --sort docs
  ```

### 3. Search Salesforce Documentation (`search`)
Executes queries semantically or lexically. You can specify limits and target collections:
```bash
./salesforce-docs search "LWC component lifecycle"
```

#### Search Options:
- **Target a specific collection** with `-c` / `--collection`:
  ```bash
  ./salesforce-docs search "custom action apex" -c developer/genai
  ```
- **Increase result limit** with `-l` / `--limit` (Default is 5):
  ```bash
  ./salesforce-docs search "Einstein Copilot setup" -l 10
  ```
- **Switch search mode** with `-m` / `--mode` (`auto`, `hybrid`, `semantic`):
  - Use `hybrid` to match exact code keywords, permission names, error logs, or snake_case/camelCase terms.
  ```bash
  ./salesforce-docs search "INVALID_FIELD_FOR_INSERT_UPDATE" -m hybrid
  ```

### 4. Retrieve Full Document Content (`fetch`)
Retrieve the complete text of any document by path identifier or URL:
```bash
./salesforce-docs fetch lwc/lwc/guides/create/create-lifecycle-hooks.html
```

#### Raw Markdown Output:
If you need to pipe the output to another tool or view the raw text:
```bash
./salesforce-docs fetch lwc/lwc/guides/create/create-lifecycle-hooks.html --raw
```
