"""JavaSetupStage: A specialized stage for setting up Java environment variables."""

import glob
import os
import xml.etree.ElementTree as ET
from typing import Any

from energytrackr.pipeline.stage_interface import PipelineStage
from energytrackr.utils.exceptions import JavaHomeNotFoundError
from energytrackr.utils.logger import logger


class JavaSetupStage(PipelineStage):
    """A specialized stage that sets JAVA_HOME or does other Java-specific tasks."""

    def run(self, context: dict[str, Any]) -> None:
        """Sets up the Java environment variables for the given commit.

        Extracts the Java version from the project's pom.xml, maps it to the
        corresponding JAVA_HOME path, and sets the environment variables.

        Args:
            context: A dictionary containing the current execution context.
        """
        if not context.get("repo_path"):
            logger.error("Repository path is not set in the configuration.", context=context)
            logger.error("Skipping Java setup stage. Defaulting to system Java.", context=context)
            return

        if not (version := self.extract_java_version("pom.xml", context)):
            logger.error("Valid Java version not found. Skipping Java setup stage.", context=context)
            logger.error("Skipping Java setup stage. Defaulting to system Java.", context=context)
            return

        java_home = self.map_version_to_home(version)
        logger.info("Setting up Java environment with JAVA_HOME: %s", java_home, context=context)

        # Update the environment variables in the parent process
        JavaEnvManager.set_java_home(java_home)
        # Log the updated environment variables
        logger.info("Updated JAVA_HOME: %s", os.environ["JAVA_HOME"], context=context)
        logger.info("Updated PATH: %s", os.environ["PATH"], context=context)

    @staticmethod
    def map_version_to_home(version: str) -> str:
        """Maps a Java version string to the corresponding JAVA_HOME path.

        For example, '1.8' is mapped to '/usr/lib/jvm/java-8-openjdk'.
        If the extracted Java version is less than 8, then it defaults to Java 8.

        Args:
            version: The extracted Java version string from the POM file.

        Returns:
            A string representing the JAVA_HOME path.
        """
        # Convert versions like "1.8" to "8"
        if version.startswith("1."):
            parts = version.split(".")
            version_number_str = parts[1] if len(parts) > 1 else version[2:]
        else:
            version_number_str = version

        try:
            version_number = int(version_number_str)
        except ValueError:
            logger.warning("Unable to parse Java version from '%s'. Defaulting to Java 8.", version)
            version_number = 8

        # If the version is less than 8, default to using Java 8.
        version_number = max(version_number, 8)

        base = f"/usr/lib/jvm/java-{version_number}-openjdk"
        # The installed directory may have an arch suffix (e.g. java-8-openjdk-amd64).
        # Prefer an exact match, then fall back to the first glob hit.
        if os.path.isdir(base):
            return base
        matches = sorted(glob.glob(f"{base}*"))
        return matches[0] if matches else base

    @staticmethod
    def extract_java_version(pom_file: str, context: dict[str, Any]) -> str | None:  # noqa: C901
        """Extracts the Java version from a Maven POM file.

        Attempts the following methods:
          1. Look for <java.version> in the <properties> section (backward compatibility).
          2. Extract a properties map and then find the Java version from the maven-compiler-plugin
             configuration (supporting <release>, <source>, and <target> tags with property resolution).
          3. Also check profiles for maven-compiler-plugin configuration.

        Args:
            pom_file (str): Path to the POM file.
            context (dict[str, Any]): The context dictionary for logging.

        Returns:
            Optional[str]: The Java version specified in the POM file, or None if not found.
        """
        # 1. Parse the POM file
        try:
            tree = ET.parse(pom_file)
        except ET.ParseError:
            logger.exception("Failed to parse pom.xml: %s", pom_file, context=context)
            return None
        except Exception:
            logger.exception("Unexpected error reading pom.xml: %s", pom_file, context=context)
            return None

        root = tree.getroot()

        # 2. Handle XML namespace
        try:
            ns = JavaSetupStage._get_xml_namespace(root)
        except Exception as e:
            logger.warning("Could not determine XML namespace, proceeding without it: %s", e, context=context)
            ns = {}

        # 3. Try extracting directly from <properties>/<java.version>
        try:
            java_version = JavaSetupStage._extract_from_properties(root, ns)
        except Exception as e:
            logger.warning("Error extracting <java.version> from properties: %s", e, context=context)
            java_version = None
        if java_version:
            return java_version

        # 4. Build the full properties map for substitution
        try:
            properties_map = JavaSetupStage._extract_properties_map(root, ns)
        except Exception as e:
            logger.warning("Error building properties map: %s", e, context=context)
            properties_map = {}

        # 5. Try maven.compiler.source/target/release shorthand properties
        try:
            java_version = JavaSetupStage._extract_from_maven_compiler_properties(properties_map)
        except Exception as e:
            logger.warning("Error extracting from maven.compiler.* properties: %s", e, context=context)
            java_version = None
        if java_version:
            return java_version

        # 6. Try the maven-compiler-plugin in the main build
        try:
            java_version = JavaSetupStage._extract_from_compiler_plugin(root, ns, properties_map)
        except Exception as e:
            logger.warning("Error extracting from compiler plugin: %s", e, context=context)
            java_version = None
        if java_version:
            return java_version

        # 7. Finally, check profiles for maven-compiler-plugin
        try:
            java_version = JavaSetupStage._extract_from_profiles(root, ns, properties_map)
        except Exception as e:
            logger.warning("Error extracting from profiles: %s", e, context=context)
            java_version = None
        if java_version:
            return java_version

        # 8. Nothing found
        logger.error("Java version not found in pom.xml: %s", pom_file, context=context)
        return None

    @staticmethod
    def _get_xml_namespace(root: ET.Element) -> dict[str, str]:
        """Extracts the XML namespace from the root element.

        Maven POM files typically include a namespace in the root element.

        Args:
            root: The root element of the XML tree.

        Returns:
            A dictionary mapping the namespace prefix to the namespace URI.
        """
        if root.tag.startswith("{"):
            uri = root.tag.split("}")[0].strip("{")
            return {"ns": uri}
        return {}

    @staticmethod
    def _extract_from_properties(root: ET.Element, ns: dict[str, str]) -> str | None:
        """Extracts the Java version from the <properties> section using the tag <java.version>.

        Args:
            root: The root element of the XML tree.
            ns: The XML namespace dictionary.

        Returns:
            The Java version string if found, otherwise None.
        """
        if (properties := root.find("ns:properties", ns)) is not None:
            java_version = properties.find("ns:java.version", ns)
            if java_version is not None and java_version.text:
                return java_version.text.strip()
        return None

    @staticmethod
    def _extract_properties_map(root: ET.Element, ns: dict[str, str]) -> dict[str, str]:
        """Extracts all properties from the <properties> section into a dictionary.

        This is used for resolving property placeholders in the POM file.

        Args:
            root: The root element of the XML tree.
            ns: The XML namespace dictionary.

        Returns:
            A dictionary mapping property names to their values.
        """
        properties = root.find("ns:properties", ns)
        result: dict[str, str] = {}
        if properties is not None:
            for child in properties:
                if child.text:
                    # Remove namespace if exists
                    tag: str = child.tag.split("}")[-1]
                    result[tag] = child.text.strip()
        return result

    @staticmethod
    def _extract_from_maven_compiler_properties(properties_map: dict[str, str]) -> str | None:
        """Extracts the Java version from Maven shorthand compiler properties.

        Maven allows configuring the compiler via properties directly in the
        <properties> section without an explicit maven-compiler-plugin block:
          <maven.compiler.release>17</maven.compiler.release>
          <maven.compiler.source>1.8</maven.compiler.source>
          <maven.compiler.target>1.8</maven.compiler.target>

        Checks keys in priority order: release > source > target.

        Args:
            properties_map: A dictionary of properties extracted from the POM file.

        Returns:
            The Java version string if found, otherwise None.
        """
        for key in ("maven.compiler.release", "maven.compiler.source", "maven.compiler.target"):
            if value := properties_map.get(key):
                return value
        return None

    @staticmethod
    def _extract_from_compiler_plugin(root: ET.Element, ns: dict[str, str], properties_map: dict[str, str]) -> str | None:
        """Extracts the Java version from the maven-compiler-plugin configuration in the main build.

        This method supports the <release> tag as well as <source> and <target> tags,
        with resolution of property placeholders.

        Args:
            root: The root element of the XML tree.
            ns: The XML namespace dictionary.
            properties_map: A dictionary of properties for resolving placeholders.

        Returns:
            The resolved Java version string if found, otherwise None.
        """
        plugins = root.findall(".//ns:plugin", ns)
        for plugin in plugins:
            if JavaSetupStage._is_maven_compiler_plugin(plugin, ns) and (
                version := JavaSetupStage._get_java_version_from_plugin(plugin, ns, properties_map)
            ):
                return version
        return None

    @staticmethod
    def _extract_from_profiles(root: ET.Element, ns: dict[str, str], properties_map: dict[str, str]) -> str | None:
        """Extracts the Java version from the maven-compiler-plugin configuration within profiles.

        Args:
            root: The root element of the XML tree.
            ns: The XML namespace dictionary.
            properties_map: A dictionary of properties for resolving placeholders.

        Returns:
            The resolved Java version string if found, otherwise None.
        """
        profiles = root.findall("ns:profiles/ns:profile", ns)
        for profile in profiles:
            if (build := profile.find("ns:build", ns)) is None:
                continue
            if (plugins := build.find("ns:plugins", ns)) is None:
                continue
            for plugin in plugins.findall("ns:plugin", ns):
                if JavaSetupStage._is_maven_compiler_plugin(plugin, ns) and (
                    version := JavaSetupStage._get_java_version_from_plugin(plugin, ns, properties_map)
                ):
                    return version
        return None

    @staticmethod
    def _is_maven_compiler_plugin(plugin: ET.Element, ns: dict[str, str]) -> bool:
        """Checks if the given plugin is the maven-compiler-plugin.

        Args:
            plugin: The plugin element to check.
            ns: The XML namespace dictionary.

        Returns:
            True if the plugin is maven-compiler-plugin, otherwise False.
        """
        artifact_id = plugin.find("ns:artifactId", ns)
        return artifact_id is not None and artifact_id.text is not None and artifact_id.text.strip() == "maven-compiler-plugin"

    @staticmethod
    def _get_java_version_from_plugin(plugin: ET.Element, ns: dict[str, str], properties: dict[str, str]) -> str | None:
        """Extracts the Java version from the maven-compiler-plugin's configuration.

        Supports tags <release>, <source>, and <target>. Resolves property placeholders
        such as ${source.version} using the provided properties dictionary. It checks both
        direct configuration and configuration within executions.

        Args:
            plugin: The maven-compiler-plugin element.
            ns: The XML namespace dictionary.
            properties: A dictionary of properties for resolving placeholders.

        Returns:
            The resolved Java version string if found, otherwise None.
        """
        # Check direct configuration element
        if ((configuration := plugin.find("ns:configuration", ns)) is not None) and (
            version := JavaSetupStage._get_version_from_configuration(configuration, ns, properties)
        ):
            return version

        # Check executions if direct configuration is not found
        if (executions := plugin.find("ns:executions", ns)) is not None:
            for execution in executions.findall("ns:execution", ns):
                if ((configuration := execution.find("ns:configuration", ns)) is not None) and (
                    version := JavaSetupStage._get_version_from_configuration(configuration, ns, properties)
                ):
                    return version

        return None

    @staticmethod
    def _get_version_from_configuration(
        configuration: ET.Element,
        ns: dict[str, str],
        properties: dict[str, str],
    ) -> str | None:
        """Helper method to extract Java version from a configuration element.

        Args:
            configuration: The configuration element to search for Java version.
            ns: The XML namespace dictionary.
            properties: A dictionary of properties for resolving placeholders.

        Returns:
            The resolved Java version string if found, otherwise None.
        """
        for tag in ("release", "source", "target"):
            logger.info("ns = %s, looking for tag: %s", ns, tag, context=None)
            logger.info("ns = %s, looking for tag: %s", ns, tag, context=None)
            version_el = configuration.find(f"ns:{tag}", ns)
            if version_el is not None and version_el.text:
                version = version_el.text.strip()
                # Resolve property if the version is in the form ${...}
                if version.startswith("${") and version.endswith("}"):
                    key = version[2:-1]
                    return properties.get(key)
                return version
        return None


class JavaEnvManager:
    """Manages JAVA_HOME and PATH environment variables for Java installations."""

    @staticmethod
    def set_java_home(java_home: str) -> None:
        """Set JAVA_HOME and update PATH by replacing any existing Java bin entries.

        This will:
        1. Remove any occurrences of the old JAVA_HOME/bin in PATH.
        2. Avoid duplicating the new java_home/bin if it's already present.
        3. Prepend the new java_home/bin to PATH.

        Args:
            java_home (str): Absolute path to the Java home directory.

        Raises:
            JavaHomeNotFoundError: If the provided java_home path does not exist.
        """
        # Validate the provided java_home
        if not os.path.isdir(java_home):
            raise JavaHomeNotFoundError(java_home)

        # Normalize the new java bin path
        new_bin: str = os.path.normpath(os.path.join(java_home, "bin"))

        # Capture and normalize the old java bin path, if JAVA_HOME was set
        old_home: str | None = os.environ.get("JAVA_HOME")
        old_bin: str | None
        old_bin = os.path.normpath(os.path.join(old_home, "bin")) if old_home else None

        # Set the new JAVA_HOME
        os.environ["JAVA_HOME"] = java_home

        # Rebuild PATH, filtering out any old or duplicate java bin entries
        original_path: str = os.environ.get("PATH", "")
        parts = original_path.split(os.pathsep)
        filtered_parts = [part for part in parts if os.path.normpath(part) not in {old_bin, new_bin}]

        # Prepend the new java bin and update PATH
        os.environ["PATH"] = os.pathsep.join([new_bin, *filtered_parts])
