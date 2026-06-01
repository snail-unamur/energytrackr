"""Unit tests for JavaSetupStage class."""

import os
from pathlib import Path

import pytest

from energytrackr.pipeline.custom_stages.java_setup_stage import JavaSetupStage


def write_pom(tmp_path: Path, content: str) -> Path:
    """Write a POM file to the specified path.

    Args:
        tmp_path (Path): The temporary path to create the POM file.
        content (str): The content to write to the POM file.

    Returns:
        Path: The path to the created POM file.
    """
    pom_path = tmp_path / "pom.xml"
    pom_path.write_text(content.strip())
    return pom_path


def test_extract_from_java_version_tag(tmp_path: str) -> None:
    """Test extracting Java version from <java.version> tag."""
    pom = """
		<project xmlns="http://maven.apache.org/POM/4.0.0">
			<properties>
				<java.version>1.8</java.version>
			</properties>
		</project>
		"""
    write_pom(tmp_path, pom)
    os.chdir(tmp_path)
    stage = JavaSetupStage()
    version = stage.extract_java_version("pom.xml", context={})
    assert version == "1.8"


def test_extract_from_compiler_plugin_source(tmp_path: str) -> None:
    """Test extracting Java version from maven-compiler-plugin source."""
    pom = """
		<project xmlns="http://maven.apache.org/POM/4.0.0">
			<build>
				<plugins>
					<plugin>
						<artifactId>maven-compiler-plugin</artifactId>
						<configuration>
							<source>11</source>
							<target>11</target>
						</configuration>
					</plugin>
				</plugins>
			</build>
		</project>
		"""
    write_pom(tmp_path, pom)
    os.chdir(tmp_path)
    stage = JavaSetupStage()
    version = stage.extract_java_version("pom.xml", context={})
    assert version == "11"


def test_extract_from_property_reference(tmp_path: str) -> None:
    """Test extracting Java version from property reference."""
    pom = """
		<project xmlns="http://maven.apache.org/POM/4.0.0">
			<properties>
				<source.version>17</source.version>
			</properties>
			<build>
				<plugins>
					<plugin>
						<artifactId>maven-compiler-plugin</artifactId>
						<configuration>
							<source>${source.version}</source>
							<target>${source.version}</target>
						</configuration>
					</plugin>
				</plugins>
			</build>
		</project>
		"""
    write_pom(tmp_path, pom)
    os.chdir(tmp_path)
    stage = JavaSetupStage()
    version = stage.extract_java_version("pom.xml", context={})
    assert version == "17"


def test_map_version_to_home_classic() -> None:
    """Test mapping Java version to home directory for classic versions."""
    result = JavaSetupStage.map_version_to_home("1.8")
    assert result.startswith("/usr/lib/jvm/java-8-openjdk")


def test_map_version_to_home_direct() -> None:
    """Test mapping Java version to home directory for direct versions."""
    result = JavaSetupStage.map_version_to_home("17")
    assert result.startswith("/usr/lib/jvm/java-17-openjdk")


def test_extract_from_profiles(tmp_path: str) -> None:
    """Test extracting Java version from profiles."""
    pom = """
		<project xmlns="http://maven.apache.org/POM/4.0.0">
			<properties>
				<target.version>21</target.version>
			</properties>
			<profiles>
				<profile>
					<build>
						<plugins>
							<plugin>
								<artifactId>maven-compiler-plugin</artifactId>
								<configuration>
									<target>${target.version}</target>
								</configuration>
							</plugin>
						</plugins>
					</build>
				</profile>
			</profiles>
		</project>
		"""
    write_pom(tmp_path, pom)
    os.chdir(tmp_path)
    stage = JavaSetupStage()
    version = stage.extract_java_version("pom.xml", context={})
    assert version == "21"


def test_extract_from_maven_compiler_properties(tmp_path: str) -> None:
    """Test extracting Java version from maven.compiler.source/target shorthand properties."""
    pom = """
		<project xmlns="http://maven.apache.org/POM/4.0.0">
			<properties>
				<maven.compiler.target>1.8</maven.compiler.target>
				<maven.compiler.source>1.8</maven.compiler.source>
			</properties>
		</project>
		"""
    write_pom(tmp_path, pom)
    os.chdir(tmp_path)
    stage = JavaSetupStage()
    version = stage.extract_java_version("pom.xml", context={})
    assert version == "1.8"


@pytest.mark.parametrize(
    "invalid_pom",
    [
        "",  # empty file
        "<notxml>",  # not valid xml
    ],
)
def test_extract_java_version_handles_invalid_files(tmp_path: str, invalid_pom: str) -> None:
    """Test that the method handles invalid POM files gracefully."""
    (tmp_path / "pom.xml").write_text(invalid_pom)
    os.chdir(tmp_path)
    stage = JavaSetupStage()
    version = stage.extract_java_version("pom.xml", context={})
    assert version is None
